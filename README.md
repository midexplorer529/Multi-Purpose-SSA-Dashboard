# 🛰️ Dynamic SSA (Space Situational Awareness) Tracker

## 📌 About the Project

Dynamic SSA Tracker is a modern web application designed to track, classify, and visualize active/inactive satellites, rocket bodies, and space debris in near real-time Earth orbit.

Originally Streamlit-based, this project has been fully redesigned with a **FastAPI** backend and **Three.js / Plotly** frontend to achieve higher performance, real-time 3D visualization, and a flexible client-server architecture.

---

## 🏗️ Technology Stack & Architecture

The application consists of two main layers: Backend (Server) and Frontend (Client).

### 1. Backend (Data Processing & API)

- **FastAPI:** High-performance, async web framework serving RESTful API endpoints.
- **Skyfield:** Computes real-time X, Y, Z coordinates and Latitude/Longitude/Altitude values from satellite TLE (Two-Line Element) data using the SGP4 (Simplified General Perturbations) model.
- **Pandas & NumPy:** Reads, cleans, and merges raw CSV files (`gp.csv` and `satcat.csv`), and computes missing orbital elements (e.g., Eccentricity) using orbital mechanics formulas.
- **Threading Cache:** A background thread refreshes satellite coordinates every 10 seconds and stores them in RAM (cache), so that user requests (15,000+ satellites) are served instantly without straining the system.

### 2. Frontend (Visualization & UI)

- **HTML/CSS/JS (Vanilla):** Fast, modern, dependency-free web interface with custom CSS (no reliance on libraries like Tailwind).
- **Three.js:** Renders all space objects in real-time on a 3D Earth globe using instanced rendering for very high performance.
- **Plotly.js:** Dynamically generates 2D map and density/distribution statistical charts (bar charts, etc.) grouped by orbit regime and country.
- **Glassmorphism UI:** A modern, semi-transparent, dark-themed UI design giving the feel of a premium space tracking control panel.

---

## 🚀 Installation & Setup

Python 3.8+ is required to run this project locally.

1. **Install Dependencies:**
   After cloning or downloading the project, navigate to the project directory in your terminal and run:
   ```bash
   pip install -r requirements.txt
   ```

2. **Prepare Data Files:**
   Make sure the latest `gp.csv` (General Perturbations/TLE) and `satcat.csv` (Satellite Catalog) files are present in the project root directory. (Up-to-date versions can be downloaded from [Celestrak](https://celestrak.org)).

3. **Start the Server:**
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000 --reload
   ```

4. **Access the Application:**
   Open your browser and go to `http://localhost:8000`.

---

## ⚙️ API Endpoints

The following endpoints are served by FastAPI:

| Endpoint | Method | Description |
|---|---|---|
| `/api/filters` | `GET` | Returns available orbit regimes, object types, and country lists to populate the frontend filter dropdowns. |
| `/api/data` | `GET` | Returns main metrics (total satellites, active, debris, etc.), table data, and statistical chart data (Plotly JSON) based on applied filters. |
| `/api/positions` | `GET` | Returns up to 300 real-time satellite positions (Lat, Lon, Altitude, Color) for the 3D globe. Unfiltered requests are served from the 10-second background cache; filtered requests are computed on-the-fly. |
| `/api/live/{norad_id}` | `GET` | Returns the current live position (latitude, longitude, elevation) of a single satellite by NORAD ID. Tries pre-parsed dict first, then Celestrak TLE, then OMM fallback. |
| `/api/track/{norad_id}` | `GET` | Computes a ground track (sequence of lat/lon coordinates) for a past and future time window. Automatically splits segments at the anti-meridian to avoid rendering artifacts. |
| `/api/trackable/{norad_id}` | `GET` | Returns whether a given NORAD ID has usable orbital elements. Used by the frontend to enable or disable the Track button. |
| `/api/space-weather` | `GET` | Fetches live Planetary K-index (Kp) from NOAA SWPC and classifies geomagnetic storm severity. Cached for 15 minutes. |
| `/api/visibility/{norad_id}` | `GET` | Checks if a satellite is currently visible (above the horizon) from a given observer location on Earth, returning topocentric elevation and azimuth. |

---

## 🔍 Orbit Classification Logic

Orbit types (LEO, MEO, GEO, etc.) are automatically determined based on the following parameters (implemented in `functions/utils.py`):

| Orbit | Condition |
|---|---|
| **HEO** (Highly Elliptical Orbit) | Eccentricity > 0.25 |
| **GEO** (Geostationary Orbit) | Mean Motion ≈ 1.0 rev/day AND Inclination < 5° |
| **GSO** (Geosynchronous Orbit) | Mean Motion ≈ 1.0 rev/day AND Inclination ≥ 5° |
| **SSO** (Sun-Synchronous Orbit) | Mean Motion > 11.25 rev/day AND 95° ≤ Inclination ≤ 105° |
| **Polar Orbit** | Mean Motion > 11.25 rev/day AND 80° ≤ Inclination ≤ 110° (outside SSO range) |
| **LEO** (Low Earth Orbit) | Mean Motion > 11.25 rev/day (other inclinations) |
| **MEO** (Medium Earth Orbit) | Does not meet any of the above conditions |

---

## 📂 Project Structure

```
web_ssa_tracker/
├── main.py               # FastAPI application, API endpoints, background cache
├── functions/
│   └── utils.py          # Data loading, orbit & object type classification
├── static/
│   ├── index.html        # Main dashboard page
│   ├── tracking.html     # Individual satellite tracking page
│   ├── css/
│   │   └── styles.css    # Application styles
│   └── js/               # Frontend JavaScript modules
├── gp.csv                # General Perturbations / TLE data (from Celestrak)
├── satcat.csv            # Satellite Catalog (from Celestrak)
└── requirements.txt      # Python dependencies
```

---

## 📦 Dependencies

```
fastapi
uvicorn
pandas
numpy
skyfield
```