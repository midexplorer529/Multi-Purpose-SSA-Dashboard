# 🚀 Dynamic SSA Tracker - Sunum ve Öğrenme Rehberi

Bu doküman, projeyi birilerine (örneğin bir mülakatta, jüriye veya ekip arkadaşlarınıza) sunarken **projeye tam anlamıyla hakim olduğunuzu** göstermeniz için hazırlanmıştır. Projenin "nasıl" ve "neden" böyle çalıştığını adım adım anlatabilmenizi sağlayacaktır.

---

## 1. Projeyi Nasıl Tanıtmalısınız? (Elevator Pitch)
*"Bu proje, Dünya yörüngesindeki uyduları, roket parçalarını ve uzay çöplerini izlemek için geliştirdiğim bir Space Situational Awareness (Uzay Durumsal Farkındalık) platformudur. Ham yörünge verilerini (TLE - Two Line Element) alıp işleyerek, yüksek performanslı 3 boyutlu ve 2 boyutlu haritalar üzerinde gerçek zamanlı yörünge takibi, bireysel uydu izleme, gözlem noktası görünürlük analizi ve analitik görselleştirmeler yapmayı sağlar."*

---

## 2. Sistemin Anatomisi (Nasıl Çalışıyor?)

Projeyi anlatırken **3 Katmanlı (Tier)** bir mimari kurduğunuzdan bahsedin:

### A. Veri Hazırlama ve Fiziksel Hesaplama (Data & Physics Layer)
- **Veri Kaynağı:** Proje `gp.csv` ve `satcat.csv` dosyalarından beslenir. Bu veriler standart uzay formatlarıdır.
- **`functions/utils.py`:** Eksik verileri tamamlar (örneğin Perigee/Apogee değerlerinden dışmerkezlik (eccentricity) hesaplama) ve uyduları fiziksel özelliklerine göre 7 sınıfa ayırır: **LEO, SSO, Polar, MEO, GEO, GSO, HEO.**
- **Skyfield Kütüphanesi:** Sadece koordinatları okumakla kalmaz, **SGP4 matematiksel modelini** kullanarak o anki zamana (`ts.now()`) göre uydunun X,Y,Z koordinatlarını ve Enlem/Boylam/İrtifa değerlerini hesaplar. *(Not: SGP4, uzay kuvvetleri tarafından kullanılan standart yörünge ilerletme (propagation) modelidir).*

### B. Sunucu ve API Katmanı (Backend Layer)
- **FastAPI:** Hız ve asenkron yapı için seçildi. İstemci (tarayıcı) doğrudan veri dosyalarını okumaz, FastAPI'den JSON formatında veri ister.
- **Arka Plan Caching (Önbellekleme):** Canlı konumları hesaplamak ağır bir işlemdir. Sunucu, `threading` kullanarak arka planda her 10 saniyede bir koordinatları hesaplayıp RAM'de saklar. Tarayıcıdan bir istek geldiğinde bekletmeden doğrudan bu önbelleği (cache) sunar. Bu, yüzlerce kullanıcının aynı anda bağlandığında sunucunun çökmesini engeller.
- **Balanced Sampling (Dengeli Örnekleme):** Performans için aynı anda haritada 300 nokta çizilir. Filtre uygulanmadığında, sunucu her yörünge rejiminden (LEO, GEO, MEO vs.) orantılı olarak uydular seçer. Böylece harita çok çeşitli ve homojen görünür. LEO filtresi uygulandığında ise sadece alçak yörüngedeki 300 uyduyu getirir.
- **Bireysel Takip (Individual Tracking):** `/api/live/{norad_id}` endpointi ile tek bir uydunun anlık konumu alınır. Veri önce yerel önbellekten, sonra CelesTrak'tan canlı TLE olarak, son olarak yerel OMM verisinden çekilir. `/api/track/{norad_id}` ile ±90 dakikalık geçmiş ve gelecek yörünge izi hesaplanır; anti-meridyen (±180° boylam) geçişlerinde parçaya bölünerek haritada yatay çizgi oluşturması engellenir.
- **Görünürlük Analizi:** `/api/visibility/{norad_id}` endpointi, belirli bir gözlem noktasından uydunun ufuk üzerinde olup olmadığını, yükseklik açısını (elevation), azimut açısını ve uzaklığını hesaplar.
- **Uzay Hava Durumu (Space Weather):** `/api/space-weather` endpointi NOAA SWPC'den Gezegen K-endeksini (Kp) çeker ve jeomanyetik fırtına şiddetini sınıflandırır. Sonuç 15 dakika önbelleklenir.

### C. Görselleştirme Katmanı (Frontend Layer)
- **Three.js (3D Dünya):** Performans darboğazını aşmak için *InstancedMesh* (Tek bir objenin yüzlerce kopyasının GPU'da çok ucuza çizilmesi) tekniği kullanıldı. Bu sayede tarayıcı kasmadan akıcı bir 3D deneyimi yaşatır.
- **Plotly.js (Grafikler & 2D):** Veri analizlerini (hangi ülkenin kaç uydusu var, hangi yörüngede ne kadar çöp var) dinamik olarak çizer.
- **Vanilla JS — `app.js`:** Ana dashboard sayfasını (`index.html`) yönetir. Herhangi bir React/Vue gibi büyük framework'e bağımlı kalmadan, doğrudan API ile iletişim kuran hızlı ve modüler bir yapı kodlandı.
- **Vanilla JS — `tracking.js`:** Bireysel uydu takip sayfasını (`tracking.html`) yönetir. Anlık konum güncelleme, geçmiş + gelecek yörünge izi çizimi, gözlem noktası seçimi ve görünürlük sorgulamasını kapsar.

---

## 3. Olası Zor Sorular ve Verilecek Mükemmel Cevaplar

> **Soru:** "Sistemdeki canlı konumlar gerçekten o anki saniyeyi mi gösteriyor?"
**Cevap:** "Evet. Uydu konumları TLE (Two Line Element) verileri üzerinden *Skyfield* kütüphanesinin *SGP4* algoritması kullanılarak tam o anki zamana göre matematiksel olarak hesaplanıyor. Sadece geçmişteki statik bir noktayı değil, o andaki fiziksel projeksiyonu görüyoruz."

> **Soru:** "Binlerce uyduyu haritada gösterirken tarayıcının donmasını nasıl engelliyorsun?"
**Cevap:** "İki farklı optimizasyonla: Birincisi backend tarafında *POSITIONS_LIMIT* kullanarak anlamlı bir alt kümeyi (balanced sampling) gönderiyorum. İkincisi, Frontend tarafında Three.js'in `InstancedMesh` yapısını kullanıyorum. Böylece tarayıcı her uydu için ayrı bir obje oluşturmak yerine, tek bir geometrinin matrisini (konumunu) güncelleyerek çizim işlemini doğrudan ekran kartına (GPU) devrediyor."

> **Soru:** "Kullanıcı filtreden 'LEO' (Alçak Yörünge) seçtiğinde arka planda tam olarak ne oluyor?"
**Cevap:** "Kullanıcı filtreyi uyguladığında, `app.js` üzerinden FastAPI'ye `?regimes=LEO` parametresiyle istek gider. Backend, önceden hazırladığı hash-map'lerden (sözlükler) çok hızlı bir şekilde (O(1) zaman karmaşıklığıyla) sadece LEO olan uyduları filtreler. Ardından bu uyduların konumlarını o anki zamana göre hesaplar ve JSON döner. Frontend ise eski harita verisini temizler ve gelen yeni konumları ekrana basar."

> **Soru:** "Proje geliştirilirken karşılaştığın en büyük teknik zorluk neydi?"
**Cevap:** "Backend'den dönen tüm uydu seçeneklerinin (örneğin LEO filtresi varken 'Choose All' yapıldığında) doğru işlenmesi süreciydi. Farklı yörüngelerdeki (HEO vb.) bozunuma uğramış bazı TLE verileri matematiksel olarak 'NaN' (Not a Number) üretebiliyordu ve bu JSON formatını bozup sunucuda 500 hatası (Internal Server Error) veriyordu. Bunu backend tarafında özel bir `math.isnan()` kontrolü yazarak ve güvenli veri gönderimi sağlayarak çözdüm."

---

## 4. Projenin Yol Haritası (Roadmap)

### ✅ Halihazırda Tamamlananlar
Aşağıdaki özellikler **projede zaten mevcuttur:**

- **Yörünge İzi Çizimi (Ground Track):** `/api/track/{norad_id}` — ±90 dakika geçmiş ve gelecek yörünge yolu hesaplanır, harita üzerinde geçmiş/gelecek olarak ayrı renklerde çizilir.
- **Gözlem Noktası Görünürlük Analizi:** `/api/visibility/{norad_id}` — belirli bir coğrafi noktadan uydunun ufuk üzerinde olup olmadığı, yükseklik ve azimut açısı hesaplanır.
- **Uzay Hava Durumu:** `/api/space-weather` — NOAA SWPC'den canlı Kp endeksi çekilir, fırtına şiddeti renk kodlu gösterilir. Sonuç 15 dakika önbelleklenir.
- **Bireysel Uydu Takip Sayfası:** `tracking.html` + `tracking.js` — konum güncelleme, yörünge izi ve görünürlük analizi entegre edilmiştir.
- **Takip Edilebilirlik Kontrolü:** `/api/trackable/{norad_id}` — frontend "Track" butonunu yalnızca kullanılabilir yörünge verisi olan objeler için aktif eder.

### 🔮 Gelecek Hedefler
Eğer "Bu projeyi daha da geliştirsen ne eklersin?" diye sorarlarsa:

1. **İstemci Tarafında (Client-side) SGP4 Yayılımı:**
   Şu an konumları Backend hesaplıyor. Gelecekte, uydu yörünge mekaniklerini WebAssembly (WASM) veya *satellite.js* ile doğrudan tarayıcı (Frontend) içine taşıyıp saniyede 60 kare (60 FPS) pürüzsüz animasyonlar yapmayı planlıyorum.
2. **Çarpışma Riski Analizi (Conjunction Assessment):**
   Uyduların yörüngelerinin kesişim noktalarını (kardinal mesafelerini) analiz edip, "Yakın zamanda çarpışma riski taşıyan objeler" adında yeni bir uyarı modülü eklemek.
3. **WebSocket Entegrasyonu:**
   Kullanıcının her 10 saniyede bir API'ye istek (pull) atması yerine, sunucunun WebSocket (push) üzerinden sadece değişen/hareket eden verileri anlık olarak istemciye göndermesi (böylece ağ yükünün azaltılması).
4. **Kapsama Alanı (Footprint) Gösterimi:**
   Uyduların Dünya yüzeyindeki iletişim konilerini (cone of visibility) harita üzerinde şeffaf bir alan olarak gösterebilmek.
5. **Pass Tahmin Modülü:**
   Seçilen gözlem noktasından, seçilen uydunun ufuk üzerine çıkacağı bir sonraki zamanları (geçiş saatleri) hesaplamak ve listelemek.
