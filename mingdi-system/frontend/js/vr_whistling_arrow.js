const VR_WHISTLING_ARROW = (function () {
    const API_BASE = "http://localhost:8000/api/v2/vr";

    let audioCtx = null;
    let activeOscillators = [];
    let isPlaying = false;

    const SHAPE_LABELS = {
        conical: "锥形",
        spherical: "球形",
        blunt: "钝头",
        ogival: "尖拱形"
    };

    function getAvailableShapes() {
        return fetch(`${API_BASE}/shapes`)
            .then(r => r.json())
            .catch(err => {
                console.log("[VRWhistlingArrow] Fetch shapes error:", err);
                return null;
            });
    }

    function estimateTrajectory(velocity, launchAngleDeg, rotationSpeed = 0.0) {
        const params = new URLSearchParams({
            velocity: velocity,
            launch_angle_deg: launchAngleDeg,
            rotation_speed: rotationSpeed
        });
        return fetch(`${API_BASE}/trajectory?${params.toString()}`)
            .then(r => r.json())
            .catch(err => {
                console.log("[VRWhistlingArrow] Trajectory error:", err);
                return null;
            });
    }

    function launch(velocity, launchAngleDeg, rotationSpeed, shapeProfile, observerDistance, observerHeadingDeg = 0.0, durationSec = 2.5) {
        const params = new URLSearchParams({
            velocity: velocity,
            launch_angle_deg: launchAngleDeg,
            rotation_speed: rotationSpeed,
            shape_profile: shapeProfile,
            observer_distance: observerDistance,
            observer_heading_deg: observerHeadingDeg,
            duration_sec: durationSec
        });
        return fetch(`${API_BASE}/launch?${params.toString()}`)
            .then(r => r.json())
            .catch(err => {
                console.log("[VRWhistlingArrow] Launch error:", err);
                return null;
            });
    }

    function launchPost(reqData) {
        return fetch(`${API_BASE}/launch`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(reqData)
        }).then(r => r.json())
          .catch(err => {
              console.log("[VRWhistlingArrow] Launch POST error:", err);
              return null;
          });
    }

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
        const adsr = params.adsr_envelope || { attack_sec: 0.05, decay_sec: 0.3, sustain_level_db: -12, release_sec: 0.15 };
        const volume = params.output_volume || 0.5;
        const vibrato = params.vibrato || { rate_hz: 3, depth_semitones: 2 };

        const attack = adsr.attack_sec || 0.05;
        const decay = adsr.decay_sec || 0.3;
        const sustain = adsr.sustain_level_db !== undefined ? Math.pow(10, adsr.sustain_level_db / 20) : 0.7;
        const release = adsr.release_sec || 0.15;

        harmonics.forEach((h, index) => {
            const osc = ctx.createOscillator();
            const gainNode = ctx.createGain();

            let freq = h.frequency_hz;
            if (h.detune_cents) {
                osc.detune.value = h.detune_cents;
            }

            osc.frequency.value = freq;
            osc.type = index === 0 ? params.waveform_type || "sawtooth" : "sine";

            const harmonicGain = h.amplitude * volume * 0.3;

            const now = ctx.currentTime;
            gainNode.gain.setValueAtTime(0, now);
            gainNode.gain.linearRampToValueAtTime(harmonicGain, now + attack);
            gainNode.gain.linearRampToValueAtTime(harmonicGain * sustain, now + attack + decay);

            const duration = params.total_duration_sec || 3.0;
            const releaseStart = now + duration - release;
            gainNode.gain.setValueAtTime(harmonicGain * sustain, releaseStart);
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

            let leftGain = gainNode;
            let rightGain = gainNode;

            if (params.binaural && params.binaural.enabled) {
                const binaural = params.binaural;
                const ild = binaural.ild_parameters || {};
                const itd = binaural.itd_parameters || {};

                const leftGainNode = ctx.createGain();
                const rightGainNode = ctx.createGain();

                const leftVol = ild.left_channel_gain !== undefined ? ild.left_channel_gain : 1.0;
                const rightVol = ild.right_channel_gain !== undefined ? ild.right_channel_gain : 1.0;

                leftGainNode.gain.value = leftVol;
                rightGainNode.gain.value = rightVol;

                const merger = ctx.createChannelMerger(2);
                gainNode.connect(leftGainNode).connect(merger, 0, 0);
                gainNode.connect(rightGainNode).connect(merger, 0, 1);
                merger.connect(ctx.destination);

                leftGain = leftGainNode;
                rightGain = rightGainNode;
            } else {
                gainNode.connect(ctx.destination);
            }

            osc.connect(gainNode);

            osc.start(now);
            osc.stop(now + duration + 0.1);

            activeOscillators.push({ oscillator: osc, gain: gainNode, leftGain: leftGain, rightGain: rightGain });
        });

        isPlaying = true;

        const btn = document.getElementById("play-whistle-btn");
        if (btn) {
            btn.textContent = "停止哨音";
            btn.classList.add("playing");
        }

        const duration = (params.total_duration_sec || 3.0) * 1000;
        setTimeout(() => {
            if (isPlaying) {
                stopWhistle();
            }
        }, duration + 200);
    }

    function drawTrajectoryPreview(canvasId, trajectorySummary, launchAngleDeg) {
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
        const angle = launchAngleDeg * Math.PI / 180 || 0.3;
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
        ctx.fillText(`${launchAngleDeg.toFixed(0)}°`, ax + arcR + 3, ay - 5);

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

    function updateLaunchDisplay(data, containerId = null) {
        const el = (id) => document.getElementById(id);
        if (!data) return;

        const audio = data.audio || {};
        const traj = data.trajectory_summary || {};
        const acoustics = data.acoustics || {};

        const freqEl = el("launch-freq");
        if (freqEl) freqEl.textContent = (audio.fundamental_frequency || 0).toFixed(0);
        const splEl = el("launch-spl");
        if (splEl) splEl.textContent = (acoustics.sound_pressure_level || audio.spl_reference_db || 0).toFixed(1);
        const timbreEl = el("launch-timbre");
        if (timbreEl) timbreEl.textContent = audio.timbre || audio.timbre_descriptor || "—";
        const rangeEl = el("launch-range");
        if (rangeEl) rangeEl.textContent = (traj.estimated_range || 0).toFixed(0);
        const altEl = el("launch-peak-alt");
        if (altEl) altEl.textContent = (traj.peak_altitude || 0).toFixed(0);

        if (audio.binaural && audio.binaural.enabled) {
            const bn = audio.binaural;
            const itdEl = el("launch-itd");
            if (itdEl) itdEl.textContent = `${bn.itd_parameters?.interaural_time_diff_us?.toFixed(0) || 0} µs`;
            const ildEl = el("launch-ild");
            if (ildEl) ildEl.textContent = `${bn.ild_parameters?.interaural_level_diff_db?.toFixed(1) || 0} dB`;
        }
    }

    return {
        getAvailableShapes,
        estimateTrajectory,
        launch,
        launchPost,
        getAudioContext,
        playWhistleFromParams,
        stopWhistle,
        drawTrajectoryPreview,
        updateLaunchDisplay,
        SHAPE_LABELS,
        isPlaying: () => isPlaying
    };
})();
