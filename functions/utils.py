import pandas as pd
def classify_orbits(row):
    mean_motion = row['MEAN_MOTION']
    inc = row['INCLINATION']
    ecc = row['ECCENTRICITY']

    if pd.isna(mean_motion):
        return "UNKNOWN"
    elif pd.notna(ecc) and ecc > 0.25:
        return "HEO"
    elif 0.98 < mean_motion < 1.02:
        if pd.notna(inc) and inc < 5:
            return "GEO"
        else:
            return "GSO"
    elif mean_motion > 11.25:
        if pd.notna(inc):
            if 95.0 <= inc <= 105:
                return "SSO"
            elif 80 <= inc <= 110:
                return "Polar"
        return "LEO"
    else:
        return "MEO"


def classify_object_types(row):
    obj = row['OBJECT_TYPE']
    status = row['OPS_STATUS_CODE']

    if obj == 'PAY':
        if status == '+':
            return "Payload / Active Satellite"
        else:
            return "Debris / Inactive Satellite"
    elif obj == 'R/B':
        return "Rocket Body"
    elif obj == 'DEB':
        return "Debris (> 10 cm)"
    else:
        return "UNKNOWN"
def load_data(gp = "gp.csv", satcat = "satcat.csv"):
    df_gp = pd.read_csv(gp, dtype=str)
    df_satcat = pd.read_csv(satcat, dtype=str)
    satcat_sub = df_satcat[['NORAD_CAT_ID', 'OBJECT_TYPE', 'OWNER', 'PERIOD', 'INCLINATION', 'APOGEE', 'PERIGEE', 'OPS_STATUS_CODE']]
    df_satcat = satcat_sub.rename(columns={'INCLINATION':'INCLINATION_SATCAT'})
    df_merged = pd.merge(df_gp, df_satcat, on='NORAD_CAT_ID', how='right')

    df_merged[['MEAN_MOTION', 'PERIOD', 'INCLINATION', 'INCLINATION_SATCAT', 'ECCENTRICITY', 'APOGEE', 'PERIGEE']] = df_merged[['MEAN_MOTION', 'PERIOD', 'INCLINATION', 'INCLINATION_SATCAT', 'ECCENTRICITY', 'APOGEE', 'PERIGEE']].apply(pd.to_numeric, errors='coerce')
    df_merged['INCLINATION'] = df_merged['INCLINATION'].fillna(df_merged['INCLINATION_SATCAT'])
    rev = 1440/df_merged['PERIOD']
    df_merged['MEAN_MOTION'] = df_merged['MEAN_MOTION'].fillna(rev)
    apogee = df_merged['APOGEE']
    perigee = df_merged['PERIGEE']
    ea_radii = 6378.137
    fill_ecc = (apogee - perigee).abs()/(apogee + perigee + 2*ea_radii)
    df_merged['ECCENTRICITY'] = df_merged['ECCENTRICITY'].fillna(fill_ecc)


    df_merged['ORBIT_REGIME'] = df_merged.apply(classify_orbits, axis=1)


    df_merged['OBJECT_TYPE_REWRITTEN'] = df_merged.apply(classify_object_types, axis=1)
    return df_merged