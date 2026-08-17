from fastapi import FastAPI, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import urllib.request
from skyfield.api import load, EarthSatellite, wgs84
import pandas as pd
import numpy as np
import time
import json
import threading
import random
import math

from functions import utils

app = FastAPI(title="Dynamic SSA API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load data at startup
print("Loading data...")
df_data = utils.load_data()
# Replace NaN with None for JSON serialization
df_data = df_data.replace({np.nan: None})
print(f"Loaded {len(df_data)} records.")

# Load gp.csv separately for real-time position calculations
# gp.csv has all required OMM fields (no nulls from the merge)
df_gp = pd.read_csv("gp.csv", dtype=str)
print(f"Loaded {len(df_gp)} TLE records for real-time tracking.")

ts = load.timescale()

# ---------------------------------------------------------------------------
# Pre-parse ALL EarthSatellite objects once at startup into a full dict
# ---------------------------------------------------------------------------
POSITIONS_LIMIT = 300
POSITIONS_REFRESH_INTERVAL = 10  # seconds

# Build per-field lookup dicts from the merged satcat so /api/positions can
# apply the same filters as /api/data without passing thousands of NORAD IDs.
_norad_to_type: dict = dict(zip(
    df_data["NORAD_CAT_ID"].astype(str),
    df_data["OBJECT_TYPE_REWRITTEN"].fillna("")
))
_norad_to_regime: dict = dict(zip(
    df_data["NORAD_CAT_ID"].astype(str),
    df_data["ORBIT_REGIME"].fillna("")
))
_norad_to_owner: dict = dict(zip(
    df_data["NORAD_CAT_ID"].astype(str),
    df_data["OWNER"].fillna("")
))

# Full satellite dict: NORAD_ID -> (EarthSatellite, name, object_type)
# All ~16k satellites parsed at startup so any filter combo returns up to POSITIONS_LIMIT.
_sat_dict: dict = {}
_sat_norad_order: list = []  # insertion order for the unfiltered default view

def _build_full_satellite_dict():
    """Parse ALL rows in gp.csv into a dict keyed by NORAD ID."""
    sat_dict = {}
    order = []
    for _, row in df_gp.iterrows():
        try:
            sat = EarthSatellite.from_omm(ts, row.to_dict())
            norad_id = str(row.get("NORAD_CAT_ID", ""))
            name = str(row.get("OBJECT_NAME", "Unknown"))
            object_type = _norad_to_type.get(norad_id, "")
            sat_dict[norad_id] = (sat, name, object_type)
            order.append(norad_id)
        except Exception:
            continue
    return sat_dict, order

print("Pre-parsing all satellites (full dict)...")
_sat_dict, _sat_norad_order = _build_full_satellite_dict()
print(f"Full satellite dict ready: {len(_sat_dict)} satellites.")

# ---------------------------------------------------------------------------
# Background position cache — refreshed every POSITIONS_REFRESH_INTERVAL s
# ---------------------------------------------------------------------------
positions_cache = {"data": None, "timestamp": 0}
_cache_lock = threading.Lock()

NATO_SET = {
    'US', 'UK', 'CA', 'IT', 'FR', 'GER', 'FGER', 'NETH', 'SPN', 'CZCH',
    'SWED', 'NOR', 'GREC', 'POR', 'TURK', 'DEN', 'LUXE', 'ROM', 'HUN',
    'POL', 'EST', 'LTU', 'BEL', 'FIN', 'SVK', 'BUL', 'SVN', 'HRV', 'MNE',
    'NATO', 'FRIT'
}

def _compute_positions(
    types: set = None,
    regimes: set = None,
    countries: set = None,
    nato_only: bool = False,
    search: str = None,
):
    """Compute real-time positions using server-side filter params.

    Filters are applied against the per-field lookup dicts (no URL size limits).
    Returns up to POSITIONS_LIMIT results.

    When NO filter is active, returns a *balanced* sample across all orbit
    regimes so that the default view is visually diverse (different altitudes).
    When a filter IS active, returns a shuffled subset so the same 300 are not
    always shown, making the visual change obvious to the user.
    """
    t = ts.now()
    has_filter = any([types, regimes, countries, nato_only, search])

    # Collect all candidate NORAD IDs that pass the filters
    candidates = []
    for norad_id in _sat_norad_order:
        if norad_id not in _sat_dict:
            continue
        # Apply filters
        if types and _norad_to_type.get(norad_id, "") not in types:
            continue
        if regimes and _norad_to_regime.get(norad_id, "") not in regimes:
            continue
        owner = _norad_to_owner.get(norad_id, "")
        if nato_only and owner not in NATO_SET:
            continue
        if countries and owner not in countries:
            continue
        if search:
            name_check = _sat_dict[norad_id][1].lower()
            if search not in name_check and search not in norad_id:
                continue
        candidates.append(norad_id)

    # --- Sampling strategy ---
    if not has_filter:
        # Balanced sample: pick proportionally from each regime so the
        # globe shows objects at various altitudes (LEO, MEO, GEO, HEO…)
        by_regime: dict[str, list] = {}
        for nid in candidates:
            r = _norad_to_regime.get(nid, "UNKNOWN")
            by_regime.setdefault(r, []).append(nid)

        selected: list[str] = []
        regimes_present = list(by_regime.keys())
        # Shuffle each bucket so we don't always get the same objects
        for bucket in by_regime.values():
            random.shuffle(bucket)

        # Round-robin across regimes until POSITIONS_LIMIT reached
        while len(selected) < POSITIONS_LIMIT and any(by_regime.values()):
            for r in list(regimes_present):
                if not by_regime.get(r):
                    continue
                selected.append(by_regime[r].pop(0))
                if len(selected) >= POSITIONS_LIMIT:
                    break
    else:
        # Filtered: shuffle so repeated requests show different subsets
        shuffled = candidates[:]
        random.shuffle(shuffled)
        selected = shuffled[:POSITIONS_LIMIT]

    # Compute live positions for the selected satellites
    results = []
    for norad_id in selected:
        sat, name, object_type = _sat_dict[norad_id]
        try:
            geocentric = sat.at(t)
            subpoint = wgs84.subpoint(geocentric)
            lat = float(subpoint.latitude.degrees)
            lon = float(subpoint.longitude.degrees)
            alt_km = float(subpoint.elevation.km)
            # NaN değerleri JSON serialize edemez — bu satırı atla
            if math.isnan(lat) or math.isnan(lon) or math.isnan(alt_km):
                continue
            color = "#22c55e" if "Payload" in object_type or "Active" in object_type else "#ef4444"
            results.append({
                "lat": lat,
                "lon": lon,
                "alt": alt_km * 1000,
                "alt_km": alt_km,
                "name": name,
                "norad_id": norad_id,
                "color": color,
            })
        except Exception:
            continue
    return {"positions": results, "count": len(results), "timestamp": time.time()}

def _background_refresh():
    """Background thread: refresh position cache every POSITIONS_REFRESH_INTERVAL seconds."""
    while True:
        try:
            payload = _compute_positions()
            with _cache_lock:
                positions_cache["data"] = payload
                positions_cache["timestamp"] = time.time()
        except Exception as exc:
            print(f"Position refresh error: {exc}")
        time.sleep(POSITIONS_REFRESH_INTERVAL)

# Compute once immediately so first request is instant, then launch background thread
print("Computing initial satellite positions...")
_initial = _compute_positions()
with _cache_lock:
    positions_cache["data"] = _initial
    positions_cache["timestamp"] = time.time()
print(f"Initial positions ready: {_initial['count']} satellites.")

_refresh_thread = threading.Thread(target=_background_refresh, daemon=True)
_refresh_thread.start()


# In-memory TLE cache: norad_id -> (fetch_time, line1, line2)
tle_cache = {}


def get_live_tle(norad_id):
    """
    Fetches the latest Two-Line Elements (TLE) from Celestrak for a given NORAD ID.
    Uses a simple in-memory cache to avoid rate-limiting if requested multiple times within an hour.
    """
    if norad_id in tle_cache:
        cache_time, l1, l2 = tle_cache[norad_id]
        if time.time() - cache_time < 3600:
            return l1, l2

    url = f"https://celestrak.org/NORAD/elements/gp.php?CATNR={norad_id}&FORMAT=tle"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            data = response.read().decode('utf-8').strip().split('\n')
        if len(data) >= 3:
            tle_cache[norad_id] = (time.time(), data[1].strip(), data[2].strip())
            return data[1].strip(), data[2].strip()
        elif len(data) == 2:
            tle_cache[norad_id] = (time.time(), data[0].strip(), data[1].strip())
            return data[0].strip(), data[1].strip()
        else:
            return None, None
    except Exception as e:
        print(f"Celestrak API error: {e}")
        return None, None

@app.get("/api/filters")
def get_filters():
    """
    Returns unique lists of orbit regimes, object types, and countries from the dataset.
    These are used to populate the dropdown filters in the frontend UI.
    """
    regime = sorted([x for x in df_data['ORBIT_REGIME'].unique() if x is not None])
    types = sorted([x for x in df_data['OBJECT_TYPE_REWRITTEN'].unique() if x is not None])
    countries = sorted([x for x in df_data['OWNER'].unique() if x is not None])
    
    return {
        "orbit_regimes": regime,
        "object_types": types,
        "countries": countries
    }

@app.get("/api/data")
def get_data(
    search: str = None,
    regimes: str = None, # comma separated
    types: str = None,   # comma separated
    countries: str = None, # comma separated
    nato_only: bool = False
):
    """
    Main endpoint for the dashboard. 
    Filters the satellite database based on query parameters and returns 
    metrics, plot data for the 3D globe, and tabular data.
    """
    df_filtered = df_data.copy()
    
    if regimes:
        regime_list = regimes.split(',')
        df_filtered = df_filtered[df_filtered['ORBIT_REGIME'].isin(regime_list)]
        
    if types:
        type_list = types.split(',')
        df_filtered = df_filtered[df_filtered['OBJECT_TYPE_REWRITTEN'].isin(type_list)]
        
    if nato_only:
        nato = [
            'US', 'UK', 'CA', 'IT', 'FR', 'GER', 'FGER', 'NETH', 'SPN', 'CZCH',
            'SWED', 'NOR', 'GREC', 'POR', 'TURK', 'DEN', 'LUXE', 'ROM', 'HUN',
            'POL', 'EST', 'LTU', 'BEL', 'FIN', 'SVK', 'BUL', 'SVN', 'HRV', 'MNE',
            'NATO', 'FRIT'
        ]
        df_filtered = df_filtered[df_filtered['OWNER'].isin(nato)]
        
    if countries:
        country_list = countries.split(',')
        df_filtered = df_filtered[df_filtered['OWNER'].isin(country_list)]
        
    if search:
        search = search.lower()
        df_filtered = df_filtered[
            df_filtered['OBJECT_NAME'].str.lower().str.contains(search, na=False) |
            df_filtered['NORAD_CAT_ID'].str.lower().str.contains(search, na=False)
        ]
        
    # Metrics should show overall data, not filtered data
    payload_count = len(df_data[df_data['OBJECT_TYPE_REWRITTEN'] == 'Payload / Active Satellite'])
    debris_count = len(df_data[df_data['OBJECT_TYPE_REWRITTEN'].isin(['Debris (> 10 cm)', 'Rocket Body', 'Debris / Inactive Satellite'])])
    
    metrics = {
        "total": len(df_data),
        "active": payload_count,
        "debris": debris_count
    }
    
    # We only need specific columns for the table and charts
    columns_shown = ['OBJECT_NAME', 'NORAD_CAT_ID', 'OBJECT_TYPE_REWRITTEN',
                     'OWNER', 'ORBIT_REGIME', 'MEAN_MOTION', 'INCLINATION', 'ECCENTRICITY']
                     
    df_plot = df_filtered.head(500).copy() # limit plot data to 500 for performance
    plot_data = []
    
    for _, row in df_plot.iterrows():
        inc = row.get('INCLINATION')
        if inc is None or pd.isna(inc): 
            inc = 90.0
            
        max_lat = inc if inc <= 90 else (180 - inc)
        lat = np.random.uniform(-max_lat, max_lat)
        lon = np.random.uniform(-180, 180)
        
        color = "#00FF00" if row['OBJECT_TYPE_REWRITTEN'] == 'Payload / Active Satellite' else "#FF0000"
        text = f"<b>{row['OBJECT_NAME']}</b><br>ID: {row['NORAD_CAT_ID']}<br>Owner: {row['OWNER']}<br>Orbit: {row['ORBIT_REGIME']}"
        
        apo = row.get('APOGEE')
        per = row.get('PERIGEE')
        alt_km = 1000.0 # Default LEO
        
        try:
            if pd.notna(apo) and pd.notna(per):
                alt_km = (float(apo) + float(per)) / 2.0
            elif pd.notna(apo):
                alt_km = float(apo)
            elif pd.notna(per):
                alt_km = float(per)
        except:
            pass
            
        alt_m = max(100000.0, alt_km * 1000.0) # Ensure it's at least 100km (space)
        
        plot_data.append({
            "lat": lat,
            "lon": lon,
            "alt": alt_m,
            "color": color,
            "text": text
        })
        
    # Orbit density chart data - using unfiltered data
    df_orbit = df_data.groupby(['ORBIT_REGIME', 'OBJECT_TYPE_REWRITTEN']).size().reset_index(name='count')
    orbit_density = df_orbit.to_dict(orient='records')
    
    # Top 5 countries chart data - using unfiltered data
    top_5 = df_data['OWNER'].value_counts().head(5).index.tolist()
    df_top = df_data[df_data['OWNER'].isin(top_5)]
    df_countries = df_top.groupby(['OWNER', 'OBJECT_TYPE_REWRITTEN']).size().reset_index(name='count')
    country_density = df_countries.to_dict(orient='records')
    
    table_data = df_filtered[columns_shown].head(500).to_dict(orient='records')
    # Tag each row: trackable=True means this object has live TLE data in _sat_dict
    for row in table_data:
        row['trackable'] = str(row.get('NORAD_CAT_ID', '')) in _sat_dict

    return {
        "metrics": metrics,
        "filtered_count": len(df_filtered),
        "plot_data": plot_data,
        "orbit_density": orbit_density,
        "country_density": country_density,
        "table_data": table_data
    }

@app.get("/api/live/{norad_id}")
def live_tracking(norad_id: str, name: str = "Target"):
    """
    Calculates the current live position (latitude, longitude, elevation) of a satellite.
    Uses pre-parsed _sat_dict first (fastest), then tries Celestrak TLE, then OMM fallback.
    Returns 404 with a clear reason if no orbital data is available.
    """
    # 1. Use pre-parsed dict (covers all 16k objects from gp.csv)
    if norad_id in _sat_dict:
        sat, _name, _otype = _sat_dict[norad_id]
        satellite = sat
    else:
        satellite = None
        # 2. Try live TLE from Celestrak
        line1, line2 = get_live_tle(norad_id)
        if line1 and line2:
            satellite = EarthSatellite(line1, line2, name, ts)
        else:
            # 3. Fallback to OMM columns in df_data (may fail for debris with missing fields)
            sat_row = df_data[df_data['NORAD_CAT_ID'] == str(norad_id)]
            if not sat_row.empty:
                try:
                    satellite = EarthSatellite.from_omm(ts, sat_row.iloc[0].to_dict())
                    satellite.name = name
                except Exception as e:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"Object {norad_id} exists in the catalog but has no trackable "
                            f"orbital elements (likely decayed debris or historical object). "
                            f"Details: {e}"
                        )
                    )

    if satellite is None:
        raise HTTPException(
            status_code=404,
            detail=f"No orbital data found for NORAD ID {norad_id}. "
                   "The object may be too old or was never tracked with TLE data."
        )

    t = ts.now()
    geocentric = satellite.at(t)
    subpoint = wgs84.subpoint(geocentric)

    return {
        "lat": float(subpoint.latitude.degrees),
        "lon": float(subpoint.longitude.degrees),
        "elevation": float(subpoint.elevation.km),
        "name": name,
        "norad_id": norad_id
    }

@app.get("/api/trackable/{norad_id}")
def check_trackable(norad_id: str):
    """
    Returns whether a given NORAD ID has usable orbital elements for real-time tracking.
    Used by the frontend to decide whether to enable or grey out the Track button.
    """
    if norad_id in _sat_dict:
        return {"trackable": True, "source": "local"}
    # Check if it at least has key OMM fields
    sat_row = df_data[df_data['NORAD_CAT_ID'] == str(norad_id)]
    if not sat_row.empty:
        row = sat_row.iloc[0]
        has_omm = pd.notna(row.get('EPOCH')) and pd.notna(row.get('MEAN_MOTION'))
        return {"trackable": has_omm, "source": "satcat" if has_omm else None}
    return {"trackable": False, "source": None}

@app.get("/api/track/{norad_id}")
def orbit_track(norad_id: str, name: str = "Target", past_minutes: int = 90, future_minutes: int = 90):
    """
    Computes a sequence of ground track coordinates (lat/lon) for a specified past and future duration.
    Automatically splits the track into separate segments if the satellite crosses the anti-meridian (180/-180 longitude)
    to prevent drawing a horizontal line across the entire map.
    """
    satellite = None
    line1, line2 = get_live_tle(norad_id)
    
    if line1 and line2:
        satellite = EarthSatellite(line1, line2, name, ts)
    else:
        sat_row = df_data[df_data['NORAD_CAT_ID'] == str(norad_id)]
        if not sat_row.empty:
            satellite = EarthSatellite.from_omm(ts, sat_row.iloc[0])
            satellite.name = name
            
    if satellite is None:
        raise HTTPException(status_code=404, detail="Orbit data not found locally or via API")
        
    t_now = ts.now()
    minutes = np.arange(-past_minutes, future_minutes + 1, 1)
    
    # ts.utc needs regular python ints or floats, np array is fine for minute but skyfield handles array of times
    t_array = ts.utc(t_now.utc.year, t_now.utc.month, t_now.utc.day, t_now.utc.hour, t_now.utc.minute + minutes, t_now.utc.second)
    
    geocentric = satellite.at(t_array)
    subpoint = wgs84.subpoint(geocentric)
    
    lats = subpoint.latitude.degrees
    lons = subpoint.longitude.degrees
    
    # Split into segments when crossing the antimeridian
    segments = []
    current_segment = []
    
    for lat, lon in zip(lats, lons):
        lat = float(lat)
        lon = float(lon)
        
        if current_segment:
            prev_lon = current_segment[-1]["lon"]
            if abs(lon - prev_lon) > 180:
                segments.append(current_segment)
                current_segment = []
                
        current_segment.append({"lat": lat, "lon": lon})
        
    if current_segment:
        segments.append(current_segment)
        
    return {"track_segments": segments}

# ---------------------------------------------------------------------------
# Real-time positions endpoint — returns instantly from cache
# ---------------------------------------------------------------------------

@app.get("/api/positions")
def get_positions(
    types: str = None,      # comma-separated OBJECT_TYPE_REWRITTEN values
    regimes: str = None,    # comma-separated ORBIT_REGIME values
    countries: str = None,  # comma-separated OWNER values
    nato_only: bool = False,
    search: str = None,
):
    """
    Returns up to 300 real-time satellite positions.
    Accepts the same filter params as /api/data so the globe always mirrors the
    table filters. Filtered requests are computed on-the-fly from the full dict;
    unfiltered requests are served from the 10-second background cache.
    """
    has_filter = any([types, regimes, countries, nato_only, search])

    if has_filter:
        return _compute_positions(
            types=set(types.split(",")) if types else None,
            regimes=set(regimes.split(",")) if regimes else None,
            countries=set(countries.split(",")) if countries else None,
            nato_only=nato_only,
            search=search.lower() if search else None,
        )

    # Unfiltered: serve from the background-refreshed cache
    with _cache_lock:
        payload = positions_cache["data"]

    if payload is None:
        payload = _compute_positions()
        with _cache_lock:
            positions_cache["data"] = payload
            positions_cache["timestamp"] = time.time()

    return payload

space_weather_cache = {
    "data": None,
    "timestamp": 0
}

@app.get("/api/space-weather")
def get_space_weather():
    """
    Fetches live Planetary K-index from NOAA SWPC.
    Classifies the severity of geomagnetic storms which can affect satellite operations (e.g. increased drag).
    Caches the result for 15 minutes.
    """
    global space_weather_cache
    
    # Cache for 15 minutes (900 seconds)
    if time.time() - space_weather_cache["timestamp"] < 900 and space_weather_cache["data"]:
        return space_weather_cache["data"]
        
    url = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            
        # The data is an array of dicts. The last element is the latest reading.
        latest = data[-1]
        time_tag = latest.get("time_tag", "Unknown")
        kp_index = float(latest.get("Kp", 0))
        
        severity = "Quiet"
        css_class = "severity-quiet"
        description = "No significant geomagnetic activity. Satellite operations nominal."
        
        if kp_index >= 9:
            severity = "Extreme Storm (G5)"
            css_class = "severity-storm-extreme"
            description = "Extreme geomagnetic storm. Satellite tracking severely degraded or lost."
        elif kp_index >= 8:
            severity = "Severe Storm (G4)"
            css_class = "severity-storm-severe"
            description = "Severe geomagnetic storm. Satellite surface charging and tracking problems expected."
        elif kp_index >= 7:
            severity = "Strong Storm (G3)"
            css_class = "severity-storm-strong"
            description = "Strong geomagnetic storm. Intermittent satellite navigation and low-frequency radio problems."
        elif kp_index >= 6:
            severity = "Moderate Storm (G2)"
            css_class = "severity-storm-moderate"
            description = "Moderate geomagnetic storm. Satellites may experience increased drag and tracking issues."
        elif kp_index >= 5:
            severity = "Minor Storm (G1)"
            css_class = "severity-storm-minor"
            description = "Minor geomagnetic storm. Weak power grid fluctuations. Minor impact on satellite operations."
        elif kp_index >= 4:
            severity = "Active"
            css_class = "severity-active"
            description = "Active geomagnetic conditions. Minor changes in orbit possible."
            
        result = {
            "kp_index": kp_index,
            "time": time_tag,
            "severity": severity,
            "css_class": css_class,
            "description": description
        }
        
        space_weather_cache["data"] = result
        space_weather_cache["timestamp"] = time.time()
        
        return result
        
    except Exception as e:
        print(f"Space Weather API error: {e}")
        return {
            "kp_index": "N/A",
            "time": "Unknown",
            "severity": "Unknown",
            "css_class": "severity-unknown",
            "description": "Could not fetch Space Weather data."
        }

@app.get("/api/visibility/{norad_id}")
def check_visibility(norad_id: str, lat: float, lon: float, name: str = "Target"):
    """
    Checks if a satellite is currently visible (above the horizon) from a specific observer location on Earth.
    Calculates the topocentric elevation and azimuth angles.
    """
    satellite = None
    line1, line2 = get_live_tle(norad_id)
    
    if line1 and line2:
        satellite = EarthSatellite(line1, line2, name, ts)
    else:
        sat_row = df_data[df_data['NORAD_CAT_ID'] == str(norad_id)]
        if not sat_row.empty:
            satellite = EarthSatellite.from_omm(ts, sat_row.iloc[0])
            satellite.name = name
            
    if satellite is None:
        raise HTTPException(status_code=404, detail="Orbit data not found locally or via API")
        
    observer = wgs84.latlon(lat, lon)
    t = ts.now()
    
    difference = satellite - observer
    topocentric = difference.at(t)
    alt, az, distance = topocentric.altaz()
    
    visible = bool(alt.degrees > 0)
    
    return {
        "visible": visible,
        "altitude_deg": float(alt.degrees),
        "azimuth_deg": float(az.degrees),
        "distance_km": float(distance.km)
    }

app.mount("/", StaticFiles(directory="static", html=True), name="static")
