import streamlit as st
import pandas as pd
import os


# --- 1. VERİ OKUMA FONKSİYONU ---
# (Streamlit'in her tıklamada dosyaları baştan okuyup çökmemesi için cache kullanıyoruz)
@st.cache_data
def load_orbital_data(gp_data='gp.csv', satcat_data='satcat.csv'):
    if not os.path.exists(gp_data) or not os.path.exists(satcat_data):
        st.error("Veri dosyaları bulunamadı!")
        st.stop()  # Hata varsa aşağıya inme, dur.

    df_gp = pd.read_csv(gp_data, dtype=str)
    df_satcat = pd.read_csv(satcat_data, dtype=str)

    satcat_subset = df_satcat[['NORAD_CAT_ID', 'OBJECT_TYPE', 'OWNER', 'LAUNCH_DATE', 'PERIOD', 'APOGEE', 'PERIGEE', 'RCS']]
    df_merged = pd.merge(df_gp, satcat_subset, how='right', on=['NORAD_CAT_ID'])

    metrics_to_convert = ['MEAN_MOTION', 'INCLINATION', 'PERIOD', 'APOGEE', 'PERIGEE', 'RCS']
    for col in metrics_to_convert:
        if col in df_merged.columns:
            df_merged[col] = pd.to_numeric(df_merged[col], errors='coerce')

    df_merged['MEAN_MOTION'] = df_merged['MEAN_MOTION'].fillna(1440 / df_merged['PERIOD'])

    def classify_orbits(mean_motion):
        if pd.isna(mean_motion):
            return "UNKNOWN"
        elif mean_motion >= 11.25:
            return "LEO"
        elif 0.98 <= mean_motion <= 1.02:
            return "GEO"
        else:
            return "MEO / OTHER"

    df_merged['ORBIT_REGIME'] = df_merged['MEAN_MOTION'].apply(classify_orbits)

    # Nesne tiplerini daha okunabilir yapalım
    type_dictionary = {'PAY': 'Payload', 'R/B': 'Rocket Body', 'DEB': 'Debris'}
    df_merged['OBJECT_TYPE_UI'] = df_merged['OBJECT_TYPE'].map(type_dictionary).fillna(df_merged['OBJECT_TYPE'])

    return df_merged


# Verimizi hafızaya alıyoruz
df_ana_tablo = load_orbital_data()

# --- 2. ARAYÜZ (UI) VE FİLTRE SEÇİM KISMI ---
st.title("🛰️ Basit Filtreleme Öğrenim Paneli")

st.sidebar.header("Filtre Menüsü")

# Adım A: Mevcut seçenekleri tablodan dinamik olarak çek
mevcut_rejimler = df_ana_tablo['ORBIT_REGIME'].dropna().unique().tolist()
mevcut_tipler = df_ana_tablo['OBJECT_TYPE_UI'].dropna().unique().tolist()

# Adım B: Ekrana açılır menüleri (multiselect) çiz ve kullanıcının seçtiklerini değişkene ata
secilen_rejim = st.sidebar.multiselect(
    "Yörünge Rejimi Seçin:",
    options=mevcut_rejimler,
    default=["LEO"]  # Sayfa ilk açıldığında otomatik LEO seçili gelsin
)

secilen_tip = st.sidebar.multiselect(
    "Nesne Tipi Seçin:",
    options=mevcut_tipler,
    default=["Payload"]
)

# --- 3. VERİYİ SÜZME (FİLTRELEME MANTIĞI) ---
# Orijinal tabloyu bozmuyoruz, kopyası üzerinde kesme biçme yapıyoruz
df_filtrelenmis = df_ana_tablo.copy()

# Eğer kullanıcı menüden bir şeyler seçtiyse filtreyi uygula:
if secilen_rejim:
    # df_filtrelenmis tablosunu güncelle: Sadece ORBIT_REGIME sütunundaki değeri, 'secilen_rejim' listesinin İÇİNDE (isin) olanları tut!
    df_filtrelenmis = df_filtrelenmis[df_filtrelenmis['ORBIT_REGIME'].isin(secilen_rejim)]

if secilen_tip:
    df_filtrelenmis = df_filtrelenmis[df_filtrelenmis['OBJECT_TYPE_UI'].isin(secilen_tip)]

# --- 4. SONUCU EKRANA YAZDIRMA ---
st.markdown("### Sonuç:")

# Elde kalan satır sayısını len() ile ölçüyoruz
toplam_sayi = len(df_filtrelenmis)

st.success(f"Şu anda seçtiğiniz kriterlerde toplam **{toplam_sayi}** adet uydu/nesne bulunmaktadır.")

# Sadece neye benzediğini görmek istersen filtrelenmiş verinin ilk 5 satırını tablo olarak basalım:
st.dataframe(df_filtrelenmis[['NORAD_CAT_ID', 'ORBIT_REGIME', 'OBJECT_TYPE_UI', 'OWNER']].head())