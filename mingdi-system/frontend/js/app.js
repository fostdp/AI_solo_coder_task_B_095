const API_BASE = "http://localhost:8000/api";

let currentArrow = "MD-001";

let currentData = {
    velocity: 65,
    rotation_speed: 100,
    altitude: 50,
    pitch: 0.3,
    whistle_frequency: 1500,
    sound_pressure_level: 85,
    estimated_range: 200,
    reynolds_number: 30000,
    drag_force: 0.15,
    lift_force: 0.08,
    drag_coefficient: 0.08,
    lift_coefficient: 0.15,
    moment: 0.02,
    strouhal_number: 0.2,
    propagation_distance: 500,
    is_alert: false
};

function init() {
    WHISTLING_ARROW_3D.init('three-canvas');
    setupUI();
    WHISTLING_ARROW_3D.updateStreamSurfaces(currentData.velocity);
    WHISTLING_ARROW_3D.setRotationSpeed(currentData.rotation_speed);
    ACOUSTIC_PANEL.drawSoundFieldCanvas('sound-field-canvas', currentData.sound_pressure_level);
    setInterval(fetchData, 2000);
    fetchConfig();
    fetchData();
}

function setupUI() {
    document.querySelectorAll('.view-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            WHISTLING_ARROW_3D.setView(btn.dataset.view);
            document.querySelectorAll('.view-btn').forEach(b => b.classList.toggle('active', b.dataset.view === btn.dataset.view));
        });
    });

    document.querySelectorAll('.arrow-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            document.querySelectorAll('.arrow-chip').forEach(c => c.classList.remove('active'));
            chip.classList.add('active');
            currentArrow = chip.dataset.arrow;
            fetchData();
        });
    });

    const velCtrl = document.getElementById('velocity-control');
    velCtrl.addEventListener('input', (e) => {
        const val = e.target.value;
        document.getElementById('vel-control-val').textContent = val + ' m/s';
        currentData.velocity = parseFloat(val);
        WHISTLING_ARROW_3D.updateStreamSurfaces(currentData.velocity);
        runSimulation();
    });

    const angleCtrl = document.getElementById('angle-control');
    angleCtrl.addEventListener('input', (e) => {
        const val = parseFloat(e.target.value);
        document.getElementById('angle-control-val').textContent = val.toFixed(2) + ' rad';
        currentData.pitch = val;
        runSimulation();
    });

    const rotCtrl = document.getElementById('rotation-control');
    rotCtrl.addEventListener('input', (e) => {
        const val = e.target.value;
        document.getElementById('rot-control-val').textContent = val + ' rad/s';
        currentData.rotation_speed = parseFloat(val);
        WHISTLING_ARROW_3D.setRotationSpeed(currentData.rotation_speed);
        runSimulation();
    });
}

function runSimulation() {
    fetch(`${API_BASE}/aerodynamics/simulate?velocity=${currentData.velocity}&angle_of_attack=${currentData.pitch}&rotation_speed=${currentData.rotation_speed}`)
        .then(r => r.json())
        .then(data => {
            currentData.drag_force = data.drag_force;
            currentData.lift_force = data.lift_force;
            currentData.moment = data.moment;
            currentData.reynolds_number = data.reynolds_number;
            currentData.drag_coefficient = data.drag_coefficient;
            currentData.lift_coefficient = data.lift_coefficient;
            updateAeroUI();
        })
        .catch(err => console.log('Aero sim error:', err));

    fetch(`${API_BASE}/acoustics/simulate?velocity=${currentData.velocity}&rotation_speed=${currentData.rotation_speed}&distance=1`)
        .then(r => r.json())
        .then(data => {
            currentData.whistle_frequency = data.whistle_frequency;
            currentData.sound_pressure_level = data.sound_pressure_level;
            currentData.propagation_distance = data.propagation_distance;
            currentData.strouhal_number = data.strouhal_number;
            WHISTLING_ARROW_3D.updateSoundField(currentData.sound_pressure_level);
            ACOUSTIC_PANEL.drawSoundFieldCanvas('sound-field-canvas', currentData.sound_pressure_level);
            ACOUSTIC_PANEL.updateAcousticsDisplay(currentData);
        })
        .catch(err => console.log('Acoustics sim error:', err));
}

function fetchData() {
    fetch(`${API_BASE}/arrow/${currentArrow}/status`)
        .then(r => {
            if (!r.ok) throw new Error('No data');
            return r.json();
        })
        .then(data => {
            currentData.velocity = data.velocity;
            currentData.rotation_speed = data.rotation_speed;
            currentData.altitude = data.altitude || 0;
            currentData.whistle_frequency = data.whistle_frequency;
            currentData.sound_pressure_level = data.sound_pressure_level;
            currentData.estimated_range = data.estimated_range;
            currentData.is_alert = data.is_alert || false;

            WHISTLING_ARROW_3D.updateStreamSurfaces(currentData.velocity);
            WHISTLING_ARROW_3D.setRotationSpeed(currentData.rotation_speed);
            WHISTLING_ARROW_3D.updateSoundField(currentData.sound_pressure_level);
            ACOUSTIC_PANEL.drawSoundFieldCanvas('sound-field-canvas', currentData.sound_pressure_level);
            ACOUSTIC_PANEL.updateAcousticsDisplay(currentData);
            updateAeroUI();
            updateGenericUI();
            updateConnectionStatus(true);
        })
        .catch(err => {
            updateConnectionStatus(false);
            runSimulation();
        });

    fetchAlerts();
}

function fetchConfig() {
    fetch(`${API_BASE}/config`)
        .then(r => r.json())
        .then(data => console.log('Config loaded:', data))
        .catch(err => console.log('Config error:', err));
}

function fetchAlerts() {
    fetch(`${API_BASE}/alerts?arrow_id=${currentArrow}&limit=10`)
        .then(r => r.json())
        .then(data => ACOUSTIC_PANEL.updateAlertsList(data.alerts || []))
        .catch(err => console.log('Alerts error:', err));
}

function updateAeroUI() {
    const el = (id) => document.getElementById(id);
    if (!el('reynolds')) return;
    el('reynolds').textContent = Math.round(currentData.reynolds_number).toLocaleString();
    el('drag-force').textContent = currentData.drag_force.toFixed(3);
    el('lift-force').textContent = currentData.lift_force.toFixed(3);
    el('drag-coef').textContent = currentData.drag_coefficient.toFixed(3);
    el('lift-coef').textContent = currentData.lift_coefficient.toFixed(3);
    el('moment').textContent = currentData.moment.toFixed(3);
}

function updateGenericUI() {
    const el = (id) => document.getElementById(id);
    if (!el('velocity')) return;
    el('velocity').textContent = currentData.velocity.toFixed(2);
    el('rotation-speed').textContent = currentData.rotation_speed.toFixed(2);
    el('altitude').textContent = (currentData.altitude || 0).toFixed(2);
    el('pitch').textContent = currentData.pitch.toFixed(4);
    el('range').textContent = currentData.estimated_range
        ? currentData.estimated_range.toFixed(1)
        : '—';
    const rangeEl = el('range');
    if (rangeEl) {
        rangeEl.classList.toggle('alert', (currentData.estimated_range || 999) < 150);
    }
}

function updateConnectionStatus(online) {
    const statusEl = document.getElementById('connection-status');
    if (!statusEl) return;
    if (online) {
        statusEl.textContent = '● 系统在线';
        statusEl.className = 'status-badge online';
    } else {
        statusEl.textContent = '● 离线模式';
        statusEl.className = 'status-badge';
    }
    const countEl = document.getElementById('sensor-count');
    if (countEl) countEl.textContent = '传感器: 3';
}

window.addEventListener('load', init);
