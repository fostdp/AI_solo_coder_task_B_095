const LAUNCH_EXPERIENCE = (function () {
    const API_BASE = "http://localhost:8000/api";

    let audioCtx = null;
    let activeOscillators = [];
    let isPlaying = false;

    const SHAPE_LABELS = {
        conical: "锥形",
        spherical: "球形",
        blunt: "钝头",
        ogival: "尖拱形"
    };

    function getAudioContext() {
        if (!audioCtx) {
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        }
        return audioCtx;
    }

    function stopWhistle() {
        activeOscillators.forEach(osc => {
            try {
                if (osc.gain) {
                    osc.gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.15);
                }
                setTimeout(() => {
                    try { osc.oscillator.stop(); } catch (e) { }
                }, 200);
            } catch (e) { }
        });
        activeOscillators = [];
        isPlaying = false;

        const btn = document.getElementById("play-whistle-btn");
        if (btn) {
            btn.textContent = "聆听哨音";
            btn.classList.remove("playing");
        }
    }

    function playWhistleFromParams(params) {
        stopWhistle();

        const ctx = getAudioContext();
        if (ctx.state === "suspended") {
            ctx.resume();
        }

        const fundamental = params.fundamental_frequency;
        const harmonics = params.harmonics || [];
        const adsr = params.adsr || { attack: 0.05, decay: 0.3, sustain: 0.7, release: 0.15 };
        const volume = params.volume || 0.5;
        const vibrato = params.vibrato || { rate_hz: 3, depth_semitones: 2 };

        harmonics.forEach((h, index) => {
            const osc = ctx.createOscillator();
            const gainNode = ctx.createGain();

            let freq = h.frequency;
            if (h.detune_cents) {
                osc.detune.value = h.detune_cents;
            }

            osc.frequency.value = freq;
            osc.type = index === 0 ? "sawtooth" : "sine";

            const harmonicGain = h.amplitude * volume * 0.3;

            const now = ctx.currentTime;
            gainNode.gain.setValueAtTime(0, now);
            gainNode.gain.linearRampToValueAtTime(harmonicGain, now + adsr.attack);
            gainNode.gain.linearRampToValueAtTime(harmonicGain * adsr.sustain, now + adsr.attack + adsr.decay);

            const duration = params.duration_seconds || 3.0;
            const releaseStart = now + duration - adsr.release;
            gainNode.gain.setValueAtTime(harmonicGain * adsr.sustain, releaseStart);
            gainNode.gain.exponentialRampToValueAtTime(0.001, now + duration);

            if (index === 0 && vibrato.rate_hz > 0) {
                const vibratoOsc = ctx.createOscillator();
                const vibratoGain = ctx.createGain();
                vibratoOsc.frequency.value = vibrato.rate_hz;
                vibratoGain.gain.value = vibrato.depth_semitones;
                vibratoOsc.connect(vibratoGain);
                vibratoGain.connect(osc.frequency);
                vibratoOsc.start(now);
                vibratoOsc.stop(now + duration);
            }

            osc.connect(gainNode);
            gainNode.connect(ctx.destination);

            osc.start(now);
            osc.stop(now + duration + 0.1);

            activeOscillators.push({ oscillator: osc, gain: gainNode });
        });

        isPlaying = true;

        const btn = document.getElementById("play-whistle-btn");
        if (btn) {
            btn.textContent = "停止哨音";
            btn.classList.add("playing");
        }

        const duration = (params.duration_seconds || 3.0) * 1000;
        setTimeout(() => {
            if (isPlaying) {
                stopWhistle();
            }
        }, duration + 200);
    }

    function fetchAudioParams(velocity, launchAngle, rotationSpeed, shapeProfile, observerDistance) {
        return fetch(`${API_BASE}/launch/audio-params?velocity=${velocity}&launch_angle=${launchAngle}&rotation_speed=${rotationSpeed}&shape_profile=${shapeProfile}&observer_distance=${observerDistance}`)
            .then(r => r.json())
            .catch(err => {
                console.log("Audio params error:", err);
                return null;
            });
    }

    function drawTrajectoryPreview(canvasId, trajectorySummary, launchAngle) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;
        const ctx = canvas.getContext("2d");
        const w = canvas.width = canvas.parentElement.clientWidth || 300;
        const h = canvas.height = 160;

        ctx.fillStyle = "#0a0e17";
        ctx.fillRect(0, 0, w, h);

        const groundY = h - 25;
        const maxRange = Math.max(trajectorySummary.estimated_range || 200, 50);
        const maxAlt = Math.max(trajectorySummary.peak_altitude || 50, 20);
        const scaleX = (w - 40) / maxRange;
        const scaleY = (groundY - 30) / maxAlt;

        ctx.strokeStyle = "#2a3a5c";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(20, groundY);
        ctx.lineTo(w - 10, groundY);
        ctx.stroke();

        ctx.fillStyle = "#1a3a1a";
        ctx.fillRect(0, groundY, w, h - groundY);

        const arrowLen = 30;
        const ax = 25;
        const ay = groundY;
        const angle = launchAngle || 0.3;
        const tipX = ax + arrowLen * Math.cos(angle);
        const tipY = ay - arrowLen * Math.sin(angle);

        ctx.strokeStyle = "#ffd700";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(ax, ay);
        ctx.lineTo(tipX, tipY);
        ctx.stroke();

        ctx.beginPath();
        ctx.arc(tipX, tipY, 3, 0, Math.PI * 2);
        ctx.fillStyle = "#ff6b6b";
        ctx.fill();

        const arcR = 25;
        ctx.strokeStyle = "#6b7c93";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.arc(ax, ay, arcR, -angle, 0);
        ctx.stroke();

        ctx.fillStyle = "#ffd700";
        ctx.font = "10px 'Microsoft YaHei', sans-serif";
        ctx.fillText(`${(angle * 180 / Math.PI).toFixed(0)}°`, ax + arcR + 3, ay - 5);

        const peakX = 20 + (maxRange / 2) * scaleX;
        const peakY = groundY - maxAlt * scaleY;
        const landX = 20 + (trajectorySummary.estimated_range || 0) * scaleX;

        ctx.strokeStyle = "#ff8c00";
        ctx.lineWidth = 1.5;
        ctx.setLineDash([4, 3]);
        ctx.beginPath();
        ctx.moveTo(ax, ay);
        ctx.quadraticCurveTo(peakX, peakY, landX, groundY);
        ctx.stroke();
        ctx.setLineDash([]);

        ctx.fillStyle = "#6b7c93";
        ctx.font = "10px 'Microsoft YaHei', sans-serif";
        ctx.textAlign = "center";
        ctx.fillText(`射程: ${(trajectorySummary.estimated_range || 0).toFixed(0)}m`, peakX, groundY + 15);
        ctx.fillText(`峰值: ${(trajectorySummary.peak_altitude || 0).toFixed(0)}m`, peakX, peakY - 8);

        const flightTime = trajectorySummary.flight_time || 0;
        ctx.textAlign = "left";
        ctx.fillText(`飞行: ${flightTime.toFixed(1)}s`, 25, groundY + 15);
    }

    function updateLaunchDisplay(data) {
        const el = (id) => document.getElementById(id);
        if (!data) return;

        const audio = data.audio || {};
        const traj = data.trajectory_summary || {};
        const acoustics = data.acoustics || {};

        const freqEl = el("launch-freq");
        if (freqEl) freqEl.textContent = (audio.fundamental_frequency || 0).toFixed(0);
        const splEl = el("launch-spl");
        if (splEl) splEl.textContent = (acoustics.sound_pressure_level || 0).toFixed(1);
        const timbreEl = el("launch-timbre");
        if (timbreEl) timbreEl.textContent = audio.timbre_descriptor || "—";
        const rangeEl = el("launch-range");
        if (rangeEl) rangeEl.textContent = (traj.estimated_range || 0).toFixed(0);
        const altEl = el("launch-peak-alt");
        if (altEl) altEl.textContent = (traj.peak_altitude || 0).toFixed(0);
    }

    return {
        getAudioContext,
        playWhistleFromParams,
        stopWhistle,
        fetchAudioParams,
        drawTrajectoryPreview,
        updateLaunchDisplay,
        SHAPE_LABELS
    };
})();
