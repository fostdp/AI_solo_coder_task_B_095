const ERA_COMPARATOR = (function () {
    const API_BASE = "http://localhost:8000/api/v2/era";

    const ERA_COLORS = {
        mingdi: "#ffd700",
        modern: "#00d4aa"
    };

    function listAvailableModels() {
        return fetch(`${API_BASE}/models`)
            .then(r => r.json())
            .catch(err => {
                console.log("[EraComparator] List models error:", err);
                return null;
            });
    }

    function compareEras(velocity, rotationSpeed, distance, modernModel, mingdiShape = "conical", modernLength = null, modernDiameter = null) {
        const params = new URLSearchParams({
            velocity: velocity,
            rotation_speed: rotationSpeed,
            distance: distance,
            modern_model: modernModel,
            mingdi_shape: mingdiShape
        });
        if (modernLength !== null) params.append("modern_whistle_length", modernLength);
        if (modernDiameter !== null) params.append("modern_whistle_diameter", modernDiameter);

        return fetch(`${API_BASE}/compare?${params.toString()}`)
            .then(r => r.json())
            .catch(err => {
                console.log("[EraComparator] Comparison error:", err);
                return null;
            });
    }

    function drawComparisonChart(canvasId, data) {
        const canvas = document.getElementById(canvasId);
        if (!canvas || !data) return;
        const ctx = canvas.getContext("2d");
        const w = canvas.width = canvas.parentElement.clientWidth || 600;
        const h = canvas.height = 350;

        ctx.fillStyle = "#0a0e17";
        ctx.fillRect(0, 0, w, h);

        const mingdi = data.mingdi || {};
        const modern = data.modern_whistle || {};
        const comp = data.comparison || {};

        const cx = w / 2;
        const cy = h / 2 - 20;
        const maxR = Math.min(w, h) * 0.3;

        ctx.font = "bold 14px 'Microsoft YaHei', sans-serif";
        ctx.textAlign = "center";

        ctx.fillStyle = ERA_COLORS.mingdi;
        ctx.fillText("古代鸣镝", cx - maxR - 20, 30);
        ctx.fillStyle = ERA_COLORS.modern;
        ctx.fillText("现代口哨", cx + maxR + 20, 30);

        const items = [
            { label: "频率 (Hz)", mingdiVal: mingdi.whistle_frequency, modernVal: modern.whistle_frequency },
            { label: "声压级 (dB)", mingdiVal: mingdi.sound_pressure_level, modernVal: modern.sound_pressure_level },
            { label: "传播距离 (m)", mingdiVal: mingdi.propagation_distance, modernVal: modern.propagation_distance },
        ];

        const itemH = 70;
        const startY = 60;

        items.forEach((item, i) => {
            const iy = startY + i * itemH;
            const mVal = item.mingdiVal || 0;
            const wVal = item.modernVal || 0;
            const maxBar = Math.max(mVal, wVal, 1);
            const barMaxW = maxR * 0.9;

            ctx.fillStyle = "#6b7c93";
            ctx.font = "11px 'Microsoft YaHei', sans-serif";
            ctx.textAlign = "center";
            ctx.fillText(item.label, cx, iy + 4);

            ctx.fillStyle = ERA_COLORS.mingdi;
            const mBarW = (mVal / maxBar) * barMaxW;
            ctx.fillRect(cx - 10 - mBarW, iy + 14, mBarW, 16);
            ctx.textAlign = "right";
            ctx.font = "10px Consolas, monospace";
            ctx.fillText(mVal.toFixed(0), cx - 14 - mBarW, iy + 27);

            ctx.fillStyle = ERA_COLORS.modern;
            const wBarW = (wVal / maxBar) * barMaxW;
            ctx.fillRect(cx + 10, iy + 14, wBarW, 16);
            ctx.textAlign = "left";
            ctx.font = "10px Consolas, monospace";
            ctx.fillText(wVal.toFixed(0), cx + 14 + wBarW, iy + 27);
        });

        if (comp.key_insight) {
            ctx.fillStyle = "#ff8c00";
            ctx.font = "12px 'Microsoft YaHei', sans-serif";
            ctx.textAlign = "center";
            const insightY = startY + items.length * itemH + 20;
            _wrapText(ctx, comp.key_insight, cx, insightY, w - 40, 18);
        }

        if (comp.era_gap_years) {
            ctx.fillStyle = "#6b7c93";
            ctx.font = "11px 'Microsoft YaHei', sans-serif";
            ctx.textAlign = "center";
            ctx.fillText(`跨时代跨度: ${comp.era_gap_years} 年`, cx, h - 15);
        }
    }

    function updateComparisonDisplay(data, containerId = "cross-era-details") {
        const container = document.getElementById(containerId);
        if (!container || !data) return;

        const m = data.mingdi || {};
        const w = data.modern_whistle || {};
        const c = data.comparison || {};

        let html = `<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">`;
        html += `<div style="padding:8px;background:#1a1408;border-radius:4px;border-left:3px solid ${ERA_COLORS.mingdi}">`;
        html += `<div style="color:${ERA_COLORS.mingdi};font-weight:600;font-size:12px">古代鸣镝</div>`;
        html += `<div style="color:#a0aec0;font-size:11px">频率: ${m.whistle_frequency?.toFixed(0) || 0} Hz</div>`;
        html += `<div style="color:#a0aec0;font-size:11px">声压级: ${m.sound_pressure_level?.toFixed(1) || 0} dB</div>`;
        html += `<div style="color:#a0aec0;font-size:11px">传播: ${m.propagation_distance?.toFixed(0) || 0} m</div>`;
        html += `<div style="color:#6b7c93;font-size:10px;margin-top:4px">机制: ${m.mechanism || ""}</div>`;
        html += `</div>`;
        html += `<div style="padding:8px;background:#081a14;border-radius:4px;border-left:3px solid ${ERA_COLORS.modern}">`;
        html += `<div style="color:${ERA_COLORS.modern};font-weight:600;font-size:12px">${w.display_name || "现代口哨"}</div>`;
        html += `<div style="color:#a0aec0;font-size:11px">频率: ${w.whistle_frequency?.toFixed(0) || 0} Hz</div>`;
        html += `<div style="color:#a0aec0;font-size:11px">声压级: ${w.sound_pressure_level?.toFixed(1) || 0} dB</div>`;
        html += `<div style="color:#a0aec0;font-size:11px">传播: ${w.propagation_distance?.toFixed(0) || 0} m</div>`;
        html += `<div style="color:#6b7c93;font-size:10px;margin-top:4px">认证: ${(w.certifications || []).join(", ")}</div>`;
        html += `</div>`;
        html += `</div>`;

        if (c.frequency_ratio_mingdi_to_modern !== undefined) {
            html += `<div style="margin-top:8px;padding:6px;background:#0a0a1a;border-radius:4px;font-size:11px;color:#a0aec0">`;
            html += `频率比: <span style="color:#ffd700">${c.frequency_ratio_mingdi_to_modern.toFixed(3)}</span> · `;
            html += `SPL差: <span style="color:#00d4aa">${c.spl_difference_db.toFixed(1)} dB</span> · `;
            html += `传播比: <span style="color:#88ccff">${c.propagation_distance_ratio.toFixed(2)}</span>`;
            html += `</div>`;
        }

        if (c.key_insight) {
            html += `<div style="margin-top:8px;padding:6px;background:#1a0a14;border-radius:4px;font-size:11px;color:#ff8c00">${c.key_insight}</div>`;
        }

        if (data.standardization_note) {
            html += `<div style="margin-top:8px;padding:6px;background:#0a141a;border-radius:4px;font-size:10px;color:#6b7c93">${data.standardization_note}</div>`;
        }

        container.innerHTML = html;
    }

    function _wrapText(ctx, text, x, y, maxWidth, lineHeight) {
        const words = text.split("");
        let line = "";
        let lineY = y;
        for (let i = 0; i < words.length; i++) {
            const testLine = line + words[i];
            const metrics = ctx.measureText(testLine);
            if (metrics.width > maxWidth && i > 0) {
                ctx.fillText(line, x, lineY);
                line = words[i];
                lineY += lineHeight;
            } else {
                line = testLine;
            }
        }
        ctx.fillText(line, x, lineY);
    }

    return {
        listAvailableModels,
        compareEras,
        drawComparisonChart,
        updateComparisonDisplay,
        ERA_COLORS
    };
})();
