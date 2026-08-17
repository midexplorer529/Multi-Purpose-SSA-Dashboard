import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

// DOM Elements
const form = document.getElementById('filter-form');
const searchInput = document.getElementById('search-input');
const regimeSelect = document.getElementById('regime-select');
const typeSelect = document.getElementById('type-select');
const natoCheckbox = document.getElementById('nato-checkbox');
const countrySelect = document.getElementById('country-select');

const metricTotal = document.getElementById('metric-total');
const metricActive = document.getElementById('metric-active');
const metricDebris = document.getElementById('metric-debris');
const tableBody = document.querySelector('#objects-table tbody');
const statusMessage = document.getElementById('status-message');
let plotData = [];
let livePositions = [];   // real-time positions from /api/positions
let positionRefreshTimer = null;
let isLiveMode = true;
let activeFilterParams = null; // null = no filter, URLSearchParams = active filter
const NATO_COUNTRIES = [
    'US', 'UK', 'CA', 'IT', 'FR', 'GER', 'FGER', 'NETH', 'SPN', 'CZCH',
    'SWED', 'NOR', 'GREC', 'POR', 'TURK', 'DEN', 'LUXE', 'ROM', 'HUN',
    'POL', 'EST', 'LTU', 'BEL', 'FIN', 'SVK', 'BUL', 'SVN', 'HRV', 'MNE',
    'NATO', 'FRIT'
];

let allCountries = [];

// Initialize
async function init() {
    try {
        const response = await fetch('/api/filters');
        const filters = await response.json();

        populateSelect(regimeSelect, filters.orbit_regimes);
        populateSelect(typeSelect, filters.object_types);

        allCountries = filters.countries;
        populateSelect(countrySelect, allCountries);

        // Setup nato checkbox listener
        natoCheckbox.addEventListener('change', () => {
            if (natoCheckbox.checked) {
                const natoOnly = allCountries.filter(c => NATO_COUNTRIES.includes(c));
                populateSelect(countrySelect, natoOnly, true);
            } else {
                populateSelect(countrySelect, allCountries, true);
            }
        });

        // Load initial data
        fetchData();
        fetchSpaceWeather();
        startLivePositions(); // start real-time position loop
    } catch (error) {
        showStatus('Error loading filters: ' + error.message, 'error');
    }
}

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
        console.error('Error fetching space weather:', error);
    }
}

function populateSelect(selectElement, options, selectAll = true) {
    selectElement.innerHTML = '';
    options.forEach(opt => {
        const option = document.createElement('option');
        option.value = opt;
        option.textContent = opt;
        if (selectAll) option.selected = true;
        selectElement.appendChild(option);
    });
}

function getSelectedValues(selectElement) {
    return Array.from(selectElement.selectedOptions).map(opt => opt.value);
}

// Handle form submit
form.addEventListener('submit', (e) => {
    e.preventDefault();
    fetchData();
});

async function fetchData() {
    showStatus('Applying filters and loading data...', 'info');

    const params = new URLSearchParams();

    let numFilters = 0;

    const search = searchInput.value.trim();
    if (search) {
        params.append('search', search);
        numFilters++;
    }

    const regimes = getSelectedValues(regimeSelect);
    const totalRegimes = regimeSelect.options.length;
    // 0 seçili = parametre gönderme (backend tümünü döndürür), uyarı göster
    if (totalRegimes > 0 && regimes.length === 0) {
        showStatus('ℹ️ Orbit Regime: No selection — showing all regimes.', 'info');
    } else if (regimes.length > 0 && regimes.length < totalRegimes) {
        params.append('regimes', regimes.join(','));
        numFilters++;
    }

    const types = getSelectedValues(typeSelect);
    const totalTypes = typeSelect.options.length;
    if (totalTypes > 0 && types.length === 0) {
        showStatus('ℹ️ Object Type: No selection — showing all types.', 'info');
    } else if (types.length > 0 && types.length < totalTypes) {
        params.append('types', types.join(','));
        numFilters++;
    }

    const countries = getSelectedValues(countrySelect);
    const totalCountries = countrySelect.options.length;
    if (totalCountries > 0 && countries.length === 0) {
        showStatus('ℹ️ Country: No selection — showing all countries.', 'info');
    } else if (countries.length > 0 && countries.length < totalCountries) {
        params.append('countries', countries.join(','));
        numFilters++;
    }

    if (natoCheckbox.checked) {
        params.append('nato_only', 'true');
        numFilters++;
    }

    try {
        const response = await fetch(`/api/data?${params.toString()}`);
        const data = await response.json();

        updateMetrics(data.metrics);
        updateTable(data.table_data);
        renderCharts(data.orbit_density, data.country_density);
        plotData = data.plot_data;

        // Store filter params for /api/positions (same params, same results)
        activeFilterParams = numFilters > 0 ? params : null;
        fetchLivePositions(); // refresh globe immediately with new filter

        showStatus(`${numFilters} filter${numFilters !== 1 ? 's' : ''} applied. A total of ${data.filtered_count} objects are listed.`, 'success');
    } catch (error) {
        showStatus('Error fetching data: ' + error.message, 'error');
    }
}

function updateMetrics(metrics) {
    metricTotal.textContent = metrics.total;
    metricActive.textContent = metrics.active;
    metricDebris.textContent = metrics.debris;
}

function updateTable(tableData) {
    tableBody.innerHTML = '';
    tableData.forEach(row => {
        const tr = document.createElement('tr');
        const trackBtn = row.trackable
            ? `<a href="/tracking.html?id=${row.NORAD_CAT_ID}&name=${encodeURIComponent(row.OBJECT_NAME || 'Unknown')}"
                  class="action-link" target="_blank">Track 🎯</a>`
            : `<span class="action-link-disabled" title="No TLE data available for this object (decayed debris or historical catalog entry)">No TLE ⚠️</span>`;
        tr.innerHTML = `
            <td>${row.OBJECT_NAME || 'Unknown'}</td>
            <td>${row.NORAD_CAT_ID}</td>
            <td>${row.OBJECT_TYPE_REWRITTEN}</td>
            <td>${row.OWNER}</td>
            <td>${row.ORBIT_REGIME}</td>
            <td>${trackBtn}</td>
        `;
        tableBody.appendChild(tr);
    });
}

function renderCharts(orbitData, countryData) {
    // Layout template
    const layoutTpl = {
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        font: { color: '#94a3b8' },
        margin: { l: 80, r: 20, t: 20, b: 40 },
        barmode: 'group'
    };

    // Prepare Orbit Data
    const orbitTraces = {};
    orbitData.forEach(d => {
        if (!orbitTraces[d.OBJECT_TYPE_REWRITTEN]) {
            orbitTraces[d.OBJECT_TYPE_REWRITTEN] = {
                y: [], x: [], type: 'bar', orientation: 'h', name: d.OBJECT_TYPE_REWRITTEN
            };
        }
        orbitTraces[d.OBJECT_TYPE_REWRITTEN].y.push(d.ORBIT_REGIME);
        orbitTraces[d.OBJECT_TYPE_REWRITTEN].x.push(d.count);
    });

    Plotly.newPlot('orbit-chart', Object.values(orbitTraces), {
        ...layoutTpl,
        yaxis: { title: 'Orbit Regime' },
        xaxis: { title: 'Number of Objects' }
    }, { displayModeBar: false, responsive: true });

    // Prepare Country Data
    const countryTraces = {};
    countryData.forEach(d => {
        if (!countryTraces[d.OBJECT_TYPE_REWRITTEN]) {
            countryTraces[d.OBJECT_TYPE_REWRITTEN] = {
                y: [], x: [], type: 'bar', orientation: 'h', name: d.OBJECT_TYPE_REWRITTEN
            };
        }
        countryTraces[d.OBJECT_TYPE_REWRITTEN].y.push(d.OWNER);
        countryTraces[d.OBJECT_TYPE_REWRITTEN].x.push(d.count);
    });

    Plotly.newPlot('country-chart', Object.values(countryTraces), {
        ...layoutTpl,
        yaxis: { title: 'Country' },
        xaxis: { title: 'Number of Objects' }
    }, { displayModeBar: false, responsive: true });
}

let threeScene, threeCamera, threeRenderer, threeGlobe, threePoints;
let orbitControls;

function initThreeJS() {
    try {
        const container = document.getElementById('globe-3d');
        container.innerHTML = '';

        threeScene = new THREE.Scene();

        const width = container.clientWidth || 800;
        const height = container.clientHeight || 500;

        threeCamera = new THREE.PerspectiveCamera(45, width / height, 0.1, 2000);
        threeCamera.position.z = 250;

        threeRenderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
        threeRenderer.setClearColor(0x000000, 1);
        threeRenderer.setSize(width, height);
        threeRenderer.setPixelRatio(window.devicePixelRatio);
        container.appendChild(threeRenderer.domElement);

        // Globe
        const globeRadius = 100;
        const sphereGeometry = new THREE.SphereGeometry(globeRadius, 64, 64);

        const textureLoader = new THREE.TextureLoader();
        const earthTexture = textureLoader.load('https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg');

        const sphereMaterial = new THREE.MeshPhongMaterial({
            map: earthTexture,
            bumpScale: 0.05,
            shininess: 5
        });
        threeGlobe = new THREE.Mesh(sphereGeometry, sphereMaterial);
        threeScene.add(threeGlobe);

        // Lighting
        const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
        threeScene.add(ambientLight);

        const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
        dirLight.position.set(5, 3, 5);
        threeScene.add(dirLight);

        // Controls
        orbitControls = new OrbitControls(threeCamera, threeRenderer.domElement);
        orbitControls.enableDamping = true;
        orbitControls.dampingFactor = 0.05;
        orbitControls.enablePan = false;
        orbitControls.minDistance = 120;
        orbitControls.maxDistance = 600;

        // Resize handler
        window.addEventListener('resize', () => {
            if (!threeRenderer || !container.clientWidth) return;
            const w = container.clientWidth;
            const h = container.clientHeight;
            threeCamera.aspect = w / h;
            threeCamera.updateProjectionMatrix();
            threeRenderer.setSize(w, h);
        });

        // Animation Loop
        function animate() {
            requestAnimationFrame(animate);
            orbitControls.update();
            threeRenderer.render(threeScene, threeCamera);
        }
        animate();

    } catch (e) {
        console.error("Three.js initialization failed", e);
    }
}

// ---------------------------------------------------------------------------
// Real-time position rendering
// ---------------------------------------------------------------------------

async function fetchLivePositions() {
    try {
        // Pass the same filter params to /api/positions (backend filters server-side)
        const qs = activeFilterParams ? activeFilterParams.toString() : '';
        const url = '/api/positions' + (qs ? `?${qs}` : '');
        console.log('[Globe] Fetching positions:', url);
        const response = await fetch(url);
        if (!response.ok) {
            console.error('[Globe] /api/positions returned', response.status);
            return;
        }
        const data = await response.json();
        livePositions = data.positions;
        renderGlobe(livePositions);
        render2DMap(livePositions);
        updateLiveBadge(data.count, activeFilterParams);
    } catch (e) {
        console.error('Live positions fetch failed:', e);
    }
}

function startLivePositions() {
    // Initialize the globe immediately so the canvas is ready
    initThreeJS();
    fetchLivePositions(); // immediate first load
    positionRefreshTimer = setInterval(fetchLivePositions, 10000); // refresh every 10s
}

function updateLiveBadge(count, filterParams) {
    const badge = document.getElementById('live-badge');
    if (!badge) return;

    // Build a human-readable filter summary for the badge
    let filterLabel = '';
    if (filterParams) {
        const parts = [];
        const regimes = filterParams.get('regimes');
        const types   = filterParams.get('types');
        const countries = filterParams.get('countries');
        const nato   = filterParams.get('nato_only');
        const search = filterParams.get('search');
        if (regimes)   parts.push(regimes.split(',').join('/')); 
        if (types)     parts.push(types.split(',').slice(0,2).join('/') + (types.split(',').length > 2 ? '…' : ''));
        if (countries) parts.push(countries.split(',').length + ' countries');
        if (nato === 'true') parts.push('NATO');
        if (search)    parts.push('"' + search + '"');
        if (parts.length) filterLabel = ' · ' + parts.join(', ');
    }

    badge.textContent = `🛰️ ${count} objects — LIVE${filterLabel}`;
}

// Shared geometry/material — created once, reused every refresh
let _sharedBoxGeometry = null;
let _sharedBoxMaterial = null;

function renderGlobe(positions) {
    // Globe must already be initialized by startLivePositions
    if (!threeScene) return;

    // Remove old instanced mesh but keep geometry/material alive
    if (threePoints) {
        threeScene.remove(threePoints);
        threePoints = null;
    }

    if (!_sharedBoxGeometry) {
        _sharedBoxGeometry = new THREE.BoxGeometry(2.5, 2.5, 2.5);
    }
    if (!_sharedBoxMaterial) {
        _sharedBoxMaterial = new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.92 });
    }

    const globeRadius = 100;
    threePoints = new THREE.InstancedMesh(_sharedBoxGeometry, _sharedBoxMaterial, positions.length);

    const dummy = new THREE.Object3D();
    const colorObj = new THREE.Color();

    positions.forEach((d, i) => {
        const altKm = (d.alt || 500000) / 1000;   // alt is in metres
        const r = globeRadius + Math.max(1, altKm / 63.71);

        const phi   = (90 - d.lat) * (Math.PI / 180);
        const theta = (d.lon + 180) * (Math.PI / 180);

        const x = -(r * Math.sin(phi) * Math.cos(theta));
        const z =  (r * Math.sin(phi) * Math.sin(theta));
        const y =  (r * Math.cos(phi));

        dummy.position.set(x, y, z);
        dummy.lookAt(0, 0, 0);
        dummy.updateMatrix();
        threePoints.setMatrixAt(i, dummy.matrix);

        colorObj.set(d.color || '#f97316');
        threePoints.setColorAt(i, colorObj);
    });

    threePoints.instanceMatrix.needsUpdate = true;
    if (threePoints.instanceColor) threePoints.instanceColor.needsUpdate = true;

    threeScene.add(threePoints);
}

function render2DMap(positions) {
    const lats   = positions.map(d => d.lat);
    const lons   = positions.map(d => d.lon);
    const colors = positions.map(d => d.color || '#f97316');
    const texts  = positions.map(d =>
        `<b>${d.name}</b><br>ID: ${d.norad_id}<br>Alt: ${d.alt_km ? d.alt_km.toFixed(1) : '?'} km`
    );

    const trace = {
        type: 'scattergeo',
        lon: lons,
        lat: lats,
        text: texts,
        hoverinfo: 'text',
        mode: 'markers',
        marker: { size: 4, color: colors, opacity: 0.85 }
    };

    const mapLayout = {
        paper_bgcolor: 'rgba(0,0,0,0)',
        margin: { l: 0, r: 0, t: 0, b: 0 },
        showlegend: false,
        geo: {
            showland: true,
            landcolor: 'rgb(20, 20, 20)',
            showocean: true,
            oceancolor: 'rgb(5, 5, 10)',
            bgcolor: 'rgba(0,0,0,0)',
            projection: { type: 'equirectangular' }
        }
    };

    Plotly.react('map-2d', [trace], mapLayout, { displayModeBar: false, responsive: true, scrollZoom: true });
}

// Legacy renderMaps — kept for compatibility but now delegates to live system
function renderMaps(pd) {
    plotData = pd;
    // Globe and 2D map are driven by fetchLivePositions; no-op here
}

function switchMapTab(tab) {
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.map-view').forEach(view => view.classList.remove('active'));

    if (tab === '3d') {
        document.querySelectorAll('.tab-btn')[0].classList.add('active');
        document.getElementById('globe-3d').classList.add('active');
        // Handle resize if switching tabs changes dimensions
        window.dispatchEvent(new Event('resize'));
    } else {
        document.querySelectorAll('.tab-btn')[1].classList.add('active');
        document.getElementById('map-2d').classList.add('active');
    }
}
window.switchMapTab = switchMapTab;

function showStatus(message, type) {
    statusMessage.textContent = message;
    statusMessage.className = 'status-message'; // clear previous
    if (type === 'error') {
        statusMessage.style.backgroundColor = 'rgba(239, 68, 68, 0.1)';
        statusMessage.style.borderColor = 'var(--danger)';
        statusMessage.style.color = 'var(--danger)';
    } else if (type === 'info') {
        statusMessage.style.backgroundColor = 'rgba(59, 130, 246, 0.1)';
        statusMessage.style.borderColor = 'var(--accent)';
        statusMessage.style.color = 'var(--accent)';
    } else {
        statusMessage.style.backgroundColor = 'rgba(16, 185, 129, 0.1)';
        statusMessage.style.borderColor = 'var(--success)';
        statusMessage.style.color = 'var(--success)';
    }
    statusMessage.classList.remove('hidden');
}

// Start
init();

// Global helpers for inline HTML event handlers

/**
 * Arama kutusuna göre seçenekleri gizler/gösterir.
 * Seçili durumlar değiştirilmez — sadece görünürlük ayarlanır.
 * Böylece arama + Choose All kombinasyonu doğru çalışır.
 */
window.filterSelectOptions = function (selectId, query) {
    const select = document.getElementById(selectId);
    if (!select) return;
    const q = query.toLowerCase().trim();
    Array.from(select.options).forEach(opt => {
        const matches = !q || opt.text.toLowerCase().includes(q);
        opt.style.display = matches ? '' : 'none';
        // NOT: Seçili duruma dokunmuyoruz — kullanıcı neyi seçtiyse o kalır
    });
};

/**
 * Görünür seçeneklerin tamamını seçer veya seçimini kaldırır.
 * Arama kutusu dolu iken sadece eşleşenleri etkiler;
 * arama kutusu boşken TÜM seçenekleri etkiler.
 */
window.selectAll = function (selectId, state) {
    const select = document.getElementById(selectId);
    if (!select) return;
    Array.from(select.options).forEach(opt => {
        // Gizli seçenekleri seçme; sadece görünür olanları etkile
        if (opt.style.display !== 'none') {
            opt.selected = state;
        }
    });
};
