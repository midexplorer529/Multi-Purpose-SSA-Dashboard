const urlParams = new URLSearchParams(window.location.search);
const targetId = urlParams.get('id');
const targetName = urlParams.get('name') || 'Target Satellite';

document.getElementById('satellite-info').textContent = `NORAD ID: ${targetId} | Target: ${targetName}`;

let map = null;
let marker = null;
let pathLine = null;
let pathCoordinates = [];
let autoPan = true;

/**
 * Fetches the live location of the target satellite from the backend API.
 * Updates the UI metrics and the map position.
 * If an observer is set, it also triggers a visibility check.
 */
async function fetchLocation() {
    const statusEl = document.getElementById('status');
    statusEl.textContent = 'Fetching location...';
    try {
        const response = await fetch(`/api/live/${targetId}?name=${encodeURIComponent(targetName)}`);
        if (!response.ok) throw new Error('Failed to fetch data');
        const data = await response.json();

        document.getElementById('lat-val').textContent = data.lat.toFixed(4) + '°';
        document.getElementById('lon-val').textContent = data.lon.toFixed(4) + '°';
        document.getElementById('alt-val').textContent = data.elevation.toFixed(2) + ' km';

        updateMap(data.lat, data.lon, data.elevation);
        
        if (document.getElementById('obs-lat')?.value && document.getElementById('obs-lon')?.value) {
            checkVisibility();
        }
        
        statusEl.textContent = `Last updated: ${new Date().toLocaleTimeString()}`;
    } catch (error) {
        statusEl.textContent = 'Error: ' + error.message;
        statusEl.style.color = 'var(--danger)';
    }
}

/**
 * Initializes or updates the Leaflet map with the latest satellite position.
 * Draws the satellite marker and its historical path.
 * Also sets up map click events for observer placement.
 * @param {number} lat - Satellite latitude
 * @param {number} lon - Satellite longitude
 * @param {number} elevation - Satellite altitude in km
 */
function updateMap(lat, lon, elevation) {
    pathCoordinates.push([lat, lon]);

    if (!map) {
        map = L.map('leaflet-map').setView([lat, lon], 4);
        // Dark theme map tiles - Esri (free, no API key required)
        L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
            attribution: 'Tiles &copy; <a href="https://www.esri.com">Esri</a> &mdash; Esri, DeLorme, NAVTEQ',
            maxZoom: 16
        }).addTo(map);

        const icon = L.icon({
            iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-red.png',
            shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
            iconSize: [25, 41],
            iconAnchor: [12, 41],
            popupAnchor: [1, -34],
            shadowSize: [41, 41]
        });

        marker = L.marker([lat, lon], { icon: icon }).addTo(map);
        marker.bindPopup(`<b>${targetName}</b><br>Altitude: ${elevation.toFixed(2)} km`);

        pathLine = L.polyline(pathCoordinates, { color: 'red', weight: 3, opacity: 0.9 }).addTo(map);

        drawPredictedTrack();

        // Disable auto-pan if user drags map
        map.on('dragstart', () => {
            autoPan = false;
            document.getElementById('refresh-btn').textContent = 'Resume Auto-Tracking';
            document.getElementById('refresh-btn').style.background = 'var(--text-secondary)';
        });

        map.on('click', (e) => {
            const { lat, lng } = e.latlng;
            const latInput = document.getElementById('obs-lat');
            if (latInput) {
                latInput.value = lat.toFixed(4);
                document.getElementById('obs-lon').value = lng.toFixed(4);
                document.getElementById('obs-preset').value = ""; // Clear preset
                updateObserverMarker(lat, lng);
                checkVisibility();
            }
        });
    } else {
        marker.setLatLng([lat, lon]);
        marker.setPopupContent(`<b>${targetName}</b><br>Altitude: ${elevation.toFixed(2)} km`);
        pathLine.setLatLngs(pathCoordinates);
        if (autoPan) {
            map.panTo([lat, lon]);
        }
    }
}

let predictedPathGroup = null;
let pendingPastSegments = null;
let pendingFutureSegments = null;

/**
 * Fetches the predicted past and future orbit track (ground track) for the satellite.
 * Parses the segments and separates them into past (yellow) and future (green) tracks.
 * Handles the anti-meridian crossing by re-segmenting the coordinates.
 */
async function fetchOrbitTrack() {
    try {
        const pastMin = 90;
        const futureMin = 90;
        const response = await fetch(`/api/track/${targetId}?name=${encodeURIComponent(targetName)}&past_minutes=${pastMin}&future_minutes=${futureMin}`);
        if (!response.ok) {
            if (response.status === 404) {
                alert("Predicted orbit API not found (404). Please stop and restart the Python backend server (main.py)!");
            }
            return;
        }
        const data = await response.json();

        let allPoints = [];
        data.track_segments.forEach(segment => {
            segment.forEach(pt => allPoints.push(pt));
        });

        const pastPoints = allPoints.slice(0, pastMin + 1);
        const futurePoints = allPoints.slice(pastMin);

        function reSegment(pts) {
            let segs = [];
            let current = [];
            for (let i = 0; i < pts.length; i++) {
                if (current.length > 0) {
                    let prevLon = current[current.length - 1].lon;
                    if (Math.abs(pts[i].lon - prevLon) > 180) {
                        segs.push(current);
                        current = [];
                    }
                }
                current.push(pts[i]);
            }
            if (current.length > 0) segs.push(current);
            return segs;
        }

        pendingPastSegments = reSegment(pastPoints).map(seg => seg.map(pt => [pt.lat, pt.lon]));
        pendingFutureSegments = reSegment(futurePoints).map(seg => seg.map(pt => [pt.lat, pt.lon]));

        if (map) {
            drawPredictedTrack();
        }
    } catch (e) {
        console.error("Failed to fetch orbit track", e);
    }
}

/**
 * Renders the fetched predicted track segments onto the map.
 * Clears any previously drawn predicted paths.
 * Past tracks are drawn in yellow, future tracks in green.
 */
function drawPredictedTrack() {
    if ((!pendingPastSegments && !pendingFutureSegments) || !map) return;

    if (predictedPathGroup) {
        map.removeLayer(predictedPathGroup);
    }

    predictedPathGroup = L.layerGroup().addTo(map);

    if (pendingPastSegments) {
        pendingPastSegments.forEach(segment => {
            L.polyline(segment, {
                color: '#eab308', // Yellow color
                weight: 2,
                opacity: 0.7,
                dashArray: '15, 8, 3, 8'
            }).addTo(predictedPathGroup);
        });
    }

    if (pendingFutureSegments) {
        pendingFutureSegments.forEach(segment => {
            L.polyline(segment, {
                color: '#22c55e', // Green color
                weight: 2,
                opacity: 0.7,
                dashArray: '15, 8, 3, 8'
            }).addTo(predictedPathGroup);
        });
    }
}

document.getElementById('refresh-btn').addEventListener('click', () => {
    autoPan = true;
    document.getElementById('refresh-btn').textContent = '📡 Auto-Tracking Active';
    document.getElementById('refresh-btn').style.background = 'var(--accent)';
    fetchLocation();
});

if (targetId) {
    document.getElementById('refresh-btn').textContent = '📡 Auto-Tracking Active';
    fetchLocation();
    fetchOrbitTrack();
    fetchSpaceWeather();
    // Auto refresh every 3 seconds for smooth real-time tracking
    setInterval(fetchLocation, 3000);
} else {
    document.getElementById('status').textContent = 'No target ID provided.';
}

/**
 * Fetches the latest space weather data (Kp index, severity) from the backend.
 * Updates the space weather alert banner in the UI with relevant warnings.
 */
async function fetchSpaceWeather() {
    try {
        const response = await fetch('/api/space-weather');
        const data = await response.json();

        const alertBanner = document.getElementById('space-weather-alert');
        const titleEl = document.getElementById('sw-title');
        const descEl = document.getElementById('sw-desc');
        const kpEl = document.getElementById('sw-kp-value');

        if (!alertBanner) return;

        titleEl.textContent = `Space Weather: ${data.severity}`;
        descEl.textContent = data.description;
        kpEl.textContent = data.kp_index;

        alertBanner.className = 'space-weather-banner';
        if (data.css_class) {
            alertBanner.classList.add(data.css_class);
        }

        alertBanner.classList.remove('hidden');
    } catch (error) {
        console.error("Error fetching space weather:", error);
    }
}

let observerMarker = null;

/**
 * Places or moves the observer marker (blue icon) on the map at the given coordinates.
 * This is used to visually indicate the location from which visibility is checked.
 * @param {number} lat - Observer latitude
 * @param {number} lon - Observer longitude
 */
function updateObserverMarker(lat, lon) {
    if (!map) return;
    if (observerMarker) {
        observerMarker.setLatLng([lat, lon]);
    } else {
        const obsIcon = L.icon({
            iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-blue.png',
            shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
            iconSize: [25, 41],
            iconAnchor: [12, 41],
            popupAnchor: [1, -34],
            shadowSize: [41, 41]
        });
        observerMarker = L.marker([lat, lon], { icon: obsIcon, title: "Observer" }).addTo(map);
        observerMarker.bindPopup("<b>Observer Station</b>");
    }
}

document.getElementById('obs-preset')?.addEventListener('change', (e) => {
    const val = e.target.value;
    if (val) {
        const [lat, lon] = val.split(',').map(Number);
        document.getElementById('obs-lat').value = lat;
        document.getElementById('obs-lon').value = lon;
        updateObserverMarker(lat, lon);
        checkVisibility();
    }
});

document.getElementById('obs-check-btn')?.addEventListener('click', () => {
    checkVisibility();
});

/**
 * Checks if the satellite is visible from the currently set observer coordinates.
 * Calls the backend API and updates the UI result panel based on the elevation and azimuth.
 * Displays "VISIBLE" (green) if above horizon, or "NOT VISIBLE" (red) if below.
 */
async function checkVisibility() {
    const latInput = document.getElementById('obs-lat')?.value;
    const lonInput = document.getElementById('obs-lon')?.value;
    
    if (!latInput || !lonInput) {
        alert("Please enter both latitude and longitude or select on the map.");
        return;
    }
    
    const lat = parseFloat(latInput);
    const lon = parseFloat(lonInput);
    updateObserverMarker(lat, lon);
    
    try {
        const response = await fetch(`/api/visibility/${targetId}?lat=${lat}&lon=${lon}&name=${encodeURIComponent(targetName)}`);
        
        const resultDiv = document.getElementById('obs-result');
        if (!resultDiv) return;
        
        if (!response.ok) {
            const errData = await response.text();
            throw new Error(`API Error: ${response.status} ${errData}`);
        }
        
        const data = await response.json();
        resultDiv.style.display = 'block';
        
        if (data.visible) {
            resultDiv.style.background = 'rgba(34, 197, 94, 0.2)'; // Green tint
            resultDiv.style.border = '1px solid rgba(34, 197, 94, 0.5)';
            resultDiv.innerHTML = `<strong>🟢 VISIBLE</strong><br>
                                   Elevation: ${data.altitude_deg.toFixed(2)}°<br>
                                   Azimuth: ${data.azimuth_deg.toFixed(2)}°<br>
                                   Distance: ${data.distance_km.toFixed(2)} km`;
        } else {
            resultDiv.style.background = 'rgba(239, 68, 68, 0.2)'; // Red tint
            resultDiv.style.border = '1px solid rgba(239, 68, 68, 0.5)';
            resultDiv.innerHTML = `<strong>🔴 NOT VISIBLE</strong> (Below horizon)<br>
                                   Elevation: ${data.altitude_deg.toFixed(2)}°<br>
                                   Azimuth: ${data.azimuth_deg.toFixed(2)}°<br>
                                   Distance: ${data.distance_km.toFixed(2)} km`;
        }
    } catch (err) {
        console.error("Visibility Error:", err);
        const resultDiv = document.getElementById('obs-result');
        if (resultDiv) {
            resultDiv.style.display = 'block';
            resultDiv.style.background = 'rgba(239, 68, 68, 0.2)';
            resultDiv.style.border = '1px solid rgba(239, 68, 68, 0.5)';
            resultDiv.innerHTML = `<strong>⚠️ Error</strong><br>${err.message}`;
        }
    }
}
