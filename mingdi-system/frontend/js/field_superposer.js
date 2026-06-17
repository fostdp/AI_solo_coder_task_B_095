const FIELD_SUPERPOSER = (function () {
    const API_BASE = "http://localhost:8000/api/v2/field";

    function getPatterns() {
        return fetch(`${API_BASE}/patterns`)
            .then(r => r.json())
            .catch(err => {
                console.log("[FieldSuperposer] Fetch patterns error:", err);
                return null;
            });
    }

    function superposeField(arrows, gridSize, gridSpacing, observerPosition, backend = "auto") {
        return fetch(`${API_BASE}/superpose`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                arrows: arrows,
                grid_size: gridSize,
                grid_spacing: gridSpacing,
                observer_position: observerPosition,
                backend: backend
            })
        }).then(r => r.json())
          .catch(err => {
              console.log("[FieldSuperposer] Superpose error:", err);
              return null;
          });
    }

    function presetField(pattern, count, velocity, rotationSpeed, spacing, backend = "auto") {
        const params = new URLSearchParams({
            pattern: pattern,
            count: count,
            velocity: velocity,
            rotation_speed: rotationSpeed,
            spacing: spacing,
            backend: backend
        });
        return fetch(`${API_BASE}/preset?${params.toString()}`)
            .then(r => r.json())
            .catch(err => {
                console.log("[FieldSuperposer] Preset error:", err);
                return null;
            });
    }

    function drawVolleyField(canvasId, result) {
        const canvas = document.getElementById(canvasId);
        if (!canvas || !result || !result.spl_grid) return;
        const ctx = canvas.getContext("2d");

        const container = canvas.parentElement;
        const w = canvas.width = container.clientWidth || 500;
        const h = canvas.height = 400;

        ctx.fillStyle = "#0a0e17";
        ctx.fillRect(0, 0, w, h);

        const field = result.spl_grid;
        const rows = field.length;
        const cols = field[0] ? field[0].length : 0;
        if (rows === 0 || cols === 0) return;

        let minSPL = Infinity, maxSPL = -Infinity;
        for (let i = 0; i < rows; i++) {
            for (let j = 0; j < cols; j++) {
                const v = field[i][j];
                if (v < minSPL) minSPL = v;
                if (v > maxSPL) maxSPL = v;
            }
        }

        const cellW = w / cols;
        const cellH = h / rows;

        for (let i = 0; i < rows; i++) {
            for (let j = 0; j < cols; j++) {
                const spl = field[i][j];
                const t = (spl - minSPL) / (maxSPL - minSPL + 0.01);
                const color = _splColorRGB(t);
                ctx.fillStyle = `rgb(${color.r},${color.g},${color.b})`;
                ctx.fillRect(j * cellW, i * cellH, cellW + 0.5, cellH + 0.5);
            }
        }

        if (result.arrow_sources) {
            const extent = result.grid_extent_m || 30.0;
            result.arrow_sources.forEach(arrow => {
                const pos = arrow.position_m || [0, 0];
                const px = (pos[0] / (extent / 2) + 1) * w / 2;
                const py = (pos[1] / (extent / 2) + 1) * h / 2;

                ctx.beginPath();
                ctx.arc(px, py, 5, 0, Math.PI * 2);
                ctx.fillStyle = "#ffd700";
                ctx.fill();
                ctx.strokeStyle = "#0a0e17";
                ctx.lineWidth = 1;
                ctx.stroke();
            });
        }

        _drawColorBar(ctx, w - 50, 30, 20, h - 60, minSPL, maxSPL);

        ctx.fillStyle = "#ffd700";
        ctx.font = "bold 13px 'Microsoft YaHei', sans-serif";
        ctx.textAlign = "left";
        ctx.fillText(`齐射声场叠加 (${result.arrow_count || 0}支)`, 10, 20);

        if (result.centroid_db !== undefined) {
            ctx.fillStyle = "#00d4aa";
            ctx.font = "11px 'Microsoft YaHei', sans-serif";
            ctx.fillText(`声心SPL: ${result.centroid_db.toFixed(1)} dB`, 10, h - 30);
        }
        if (result.total_acoustic_power_w !== undefined) {
            ctx.fillStyle = "#88ccff";
            ctx.fillText(`总声功率: ${result.total_acoustic_power_w.toFixed(3)} W`, 10, h - 10);
        }
    }

    function _drawColorBar(ctx, x, y, width, height, minVal, maxVal) {
        for (let i = 0; i < height; i++) {
            const t = 1 - i / height;
            const color = _splColorRGB(t);
            ctx.fillStyle = `rgb(${color.r},${color.g},${color.b})`;
            ctx.fillRect(x, y + i, width, 1);
        }

        ctx.fillStyle = "#e0e6ed";
        ctx.font = "10px Consolas, monospace";
        ctx.textAlign = "left";
        ctx.fillText(`${maxVal.toFixed(0)} dB`, x + width + 4, y + 10);
        ctx.fillText(`${minVal.toFixed(0)} dB`, x + width + 4, y + height);
        ctx.fillText(`${((maxVal + minVal) / 2).toFixed(0)} dB`, x + width + 4, y + height / 2 + 4);
    }

    function _splColorRGB(t) {
        let r, g, b;
        if (t < 0.25) {
            r = 0; g = Math.round(25 + t * 680); b = Math.round(80 + t * 280);
        } else if (t < 0.5) {
            const tt = (t - 0.25) / 0.25;
            r = 0; g = Math.round(50 + tt * 150); b = Math.round(150 - tt * 75);
        } else if (t < 0.75) {
            const tt = (t - 0.5) / 0.25;
            r = Math.round(tt * 255); g = Math.round(200 - tt * 75); b = Math.round(75 - tt * 50);
        } else {
            const tt = (t - 0.75) / 0.25;
            r = 255; g = Math.round(125 - tt * 100); b = Math.round(25 - tt * 25);
        }
        return { r, g, b };
    }

    function updateVolleyInfo(result, containerId = "volley-info") {
        const container = document.getElementById(containerId);
        if (!container || !result) return;

        let html = `<div style="font-size:12px;color:#a0aec0">`;
        html += `<div>箭数: <span style="color:#ffd700">${result.arrow_count || 0}</span></div>`;
        html += `<div>网格: <span style="color:#e0e6ed">${result.grid_size || 0}×${result.grid_size || 0}</span></div>`;
        html += `<div>声心SPL: <span style="color:#00d4aa">${result.centroid_db?.toFixed(1) || 0} dB</span></div>`;
        html += `<div>总声功率: <span style="color:#88ccff">${result.total_acoustic_power_w?.toFixed(3) || 0} W</span></div>`;
        html += `<div>计算耗时: <span style="color:#e0e6ed">${result.computation_ms?.toFixed(0) || 0} ms</span></div>`;
        html += `<div>后端: <span style="color:#ffd700">${result.acoustic_backend || "numpy"}</span></div>`;

        if (result.interference_regions && result.interference_regions.length > 0) {
            html += `<div style="margin-top:8px;color:#6b7c93;font-weight:600">干涉区域分析:</div>`;
            result.interference_regions.forEach(reg => {
                const color = reg.type === "constructive" ? "#00d4aa" : "#ff6b6b";
                const label = reg.type === "constructive" ? "建设性" : "破坏性";
                html += `<div style="color:${color};font-size:11px">${label}: ${Math.round(reg.grid_ratio * 100)}% 网格</div>`;
            });
        }

        if (result.audio_synthesis) {
            html += `<div style="margin-top:8px;padding:6px;background:#0a1a14;border-radius:4px">`;
            html += `<div style="color:#00d4aa;font-size:11px;font-weight:600">双耳音频参数就绪</div>`;
            html += `<div style="color:#a0aec0;font-size:10px">主频: ${result.audio_synthesis.fundamental_frequency?.toFixed(0) || 0} Hz</div>`;
            if (result.audio_synthesis.binaural) {
                html += `<div style="color:#ffd700;font-size:10px">ITD: ${result.audio_synthesis.binaural.itd_parameters?.interaural_time_diff_us?.toFixed(0) || 0} µs</div>`;
            }
            html += `</div>`;
        }

        if (result.performance_hint) {
            html += `<div style="margin-top:8px;padding:4px;background:#1a1408;border-radius:4px;font-size:10px;color:#ffd700">${result.performance_hint}</div>`;
        }

        html += `</div>`;
        container.innerHTML = html;
    }

    return {
        getPatterns,
        superposeField,
        presetField,
        drawVolleyField,
        updateVolleyInfo
    };
})();
