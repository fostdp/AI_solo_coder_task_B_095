const API_BASE = "http://localhost:8000/api";

let currentArrow = "MD-001";
let currentVolleyPattern = "line";

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

let launchAudioData = null;

function init() {
    WHISTLING_ARROW_3D.init('three-canvas');
    setupUI();
    setupNewFeatureUI();
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

function setupNewFeatureUI() {
    document.querySelectorAll('.nav-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            tab.classList.add('active');
            document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
        });
    });

    setupShapeComparisonUI();
    setupCrossEraUI();
    setupVolleyUI();
    setupLaunchUI();
}

function setupShapeComparisonUI() {
    const velSlider = document.getElementById('shape-vel');
    const aoaSlider = document.getElementById('shape-aoa');
    const rotSlider = document.getElementById('shape-rot');

    if (velSlider) velSlider.addEventListener('input', (e) => {
        document.getElementById('shape-vel-val').textContent = e.target.value + ' m/s';
    });
    if (aoaSlider) aoaSlider.addEventListener('input', (e) => {
        document.getElementById('shape-aoa-val').textContent = parseFloat(e.target.value).toFixed(2) + ' rad';
    });
    if (rotSlider) rotSlider.addEventListener('input', (e) => {
        document.getElementById('shape-rot-val').textContent = e.target.value + ' rad/s';
    });

    const runBtn = document.getElementById('run-shape-comparison');
    if (runBtn) runBtn.addEventListener('click', () => {
        const vel = parseFloat(document.getElementById('shape-vel').value);
        const aoa = parseFloat(document.getElementById('shape-aoa').value);
        const rot = parseFloat(document.getElementById('shape-rot').value);
        SHAPE_COMPARATOR.compareShapes(vel, ["conical", "spherical", "blunt", "ogival"], aoa, rot, true)
            .then(data => {
                if (data && data.comparison) {
                    SHAPE_COMPARATOR.drawComparisonChart('shape-comparison-chart', data.comparison);
                    SHAPE_COMPARATOR.updateComparisonDisplay(data);
                }
            });
    });
}

function setupCrossEraUI() {
    const velSlider = document.getElementById('era-vel');
    const rotSlider = document.getElementById('era-rot');
    const distSlider = document.getElementById('era-dist');

    if (velSlider) velSlider.addEventListener('input', (e) => {
        document.getElementById('era-vel-val').textContent = e.target.value + ' m/s';
    });
    if (rotSlider) rotSlider.addEventListener('input', (e) => {
        document.getElementById('era-rot-val').textContent = e.target.value + ' rad/s';
    });
    if (distSlider) distSlider.addEventListener('input', (e) => {
        document.getElementById('era-dist-val').textContent = e.target.value + ' m';
    });

    const runBtn = document.getElementById('run-cross-era');
    if (runBtn) runBtn.addEventListener('click', () => {
        const vel = parseFloat(document.getElementById('era-vel').value);
        const rot = parseFloat(document.getElementById('era-rot').value);
        const dist = parseFloat(document.getElementById('era-dist').value);
        ERA_COMPARATOR.compareEras(vel, rot, dist, "fox40_classic", "conical")
            .then(data => {
                if (data) {
                    ERA_COMPARATOR.drawComparisonChart('cross-era-chart', data);
                    ERA_COMPARATOR.updateComparisonDisplay(data);
                }
            });
    });
}

function setupVolleyUI() {
    document.querySelectorAll('[data-pattern]').forEach(chip => {
        chip.addEventListener('click', () => {
            document.querySelectorAll('[data-pattern]').forEach(c => c.classList.remove('active'));
            chip.classList.add('active');
            currentVolleyPattern = chip.dataset.pattern;
        });
    });

    const countSlider = document.getElementById('volley-count');
    const velSlider = document.getElementById('volley-vel');
    const spacingSlider = document.getElementById('volley-spacing');

    if (countSlider) countSlider.addEventListener('input', (e) => {
        document.getElementById('volley-count-val').textContent = e.target.value;
    });
    if (velSlider) velSlider.addEventListener('input', (e) => {
        document.getElementById('volley-vel-val').textContent = e.target.value + ' m/s';
    });
    if (spacingSlider) spacingSlider.addEventListener('input', (e) => {
        document.getElementById('volley-spacing-val').textContent = e.target.value + ' m';
    });

    const runBtn = document.getElementById('run-volley');
    if (runBtn) runBtn.addEventListener('click', () => {
        const count = parseInt(document.getElementById('volley-count').value);
        const vel = parseFloat(document.getElementById('volley-vel').value);
        const spacing = parseFloat(document.getElementById('volley-spacing').value);
        FIELD_SUPERPOSER.presetField(currentVolleyPattern, count, vel, 100, spacing, "auto")
            .then(data => {
                if (data) {
                    FIELD_SUPERPOSER.drawVolleyField('volley-field-canvas', data);
                    FIELD_SUPERPOSER.updateVolleyInfo(data);
                }
            });
    });
}

function setupLaunchUI() {
    const angleSlider = document.getElementById('launch-angle');
    const velSlider = document.getElementById('launch-vel');
    const rotSlider = document.getElementById('launch-rot');
    const distSlider = document.getElementById('launch-dist');

    if (angleSlider) angleSlider.addEventListener('input', (e) => {
        document.getElementById('launch-angle-val').textContent = e.target.value + '°';
        updateLaunchPreview();
    });
    if (velSlider) velSlider.addEventListener('input', (e) => {
        document.getElementById('launch-vel-val').textContent = e.target.value + ' m/s';
        updateLaunchPreview();
    });
    if (rotSlider) rotSlider.addEventListener('input', (e) => {
        document.getElementById('launch-rot-val').textContent = e.target.value + ' rad/s';
    });
    if (distSlider) distSlider.addEventListener('input', (e) => {
        document.getElementById('launch-dist-val').textContent = e.target.value + ' m';
    });

    const playBtn = document.getElementById('play-whistle-btn');
    if (playBtn) playBtn.addEventListener('click', () => {
        if (VR_WHISTLING_ARROW.isPlaying()) {
            VR_WHISTLING_ARROW.stopWhistle();
            return;
        }
        if (launchAudioData && launchAudioData.audio) {
            VR_WHISTLING_ARROW.playWhistleFromParams(launchAudioData.audio);
        } else {
            updateLaunchPreview(() => {
                if (launchAudioData && launchAudioData.audio) {
                    VR_WHISTLING_ARROW.playWhistleFromParams(launchAudioData.audio);
                }
            });
        }
    });

    updateLaunchPreview();
}

function updateLaunchPreview(callback) {
    const angleDeg = parseFloat(document.getElementById('launch-angle').value);
    const vel = parseFloat(document.getElementById('launch-vel').value);
    const rot = parseFloat(document.getElementById('launch-rot').value);
    const shape = document.getElementById('launch-shape').value;
    const dist = parseFloat(document.getElementById('launch-dist').value);

    VR_WHISTLING_ARROW.launch(vel, angleDeg, rot, shape, dist, 0.0, 2.5)
        .then(data => {
            if (data) {
                launchAudioData = { audio: data.audio, trajectory_summary: data.trajectory_summary || {}, acoustics: data.acoustics || {} };
                VR_WHISTLING_ARROW.drawTrajectoryPreview('trajectory-canvas', data.trajectory_summary || {}, angleDeg);
                VR_WHISTLING_ARROW.updateLaunchDisplay(launchAudioData);
            }
            if (callback) callback();
        })
        .catch(err => {
            console.log('Launch preview error:', err);
            if (callback) callback();
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
