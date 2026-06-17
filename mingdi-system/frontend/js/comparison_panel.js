const COMPARISON_PANEL = (function () {
    const API_BASE = "http://localhost:8000/api";

    const SHAPE_LABELS = {
        conical: "锥形",
        spherical: "球形",
        blunt: "钝头",
        ogival: "尖拱形"
    };

    const SHAPE_COLORS = {
        conical: "#00d4aa",
        spherical: "#ffd700",
        blunt: "#ff6b6b",
        ogival: "#88ccff"
    };

    function fetchShapeComparison(velocity, shapes, aoa, rotation) {
        const shapesParam = shapes.join(",");
        return fetch(`${API_BASE}/shapes/compare?velocity=${velocity}&shapes=${shapesParam}&angle_of_attack=${aoa}&rotation_speed=${rotation}`)
            .then(r => r.json())
            .catch(err => {
                console.log("Shape comparison error:", err);
                return null;
            });
    }

    function fetchCrossEraComparison(velocity, rotationSpeed, distance) {
        return fetch(`${API_BASE}/acoustics/cross-era-comparison?velocity=${velocity}&rotation_speed=${rotationSpeed}&distance=${distance}`)
            .then(r => r.json())
            .catch(err => {
                console.log("Cross-era comparison error:", err);
                return null;
            });
    }

    function drawShapeComparisonChart(canvasId, comparison) {
        const canvas = document.getElementById(canvasId);
        if (!canvas || !comparison) return;
        const ctx = canvas.getContext("2d");
        const w = canvas.width = canvas.parentElement.clientWidth || 600;
        const h = canvas.height = 350;

        ctx.fillStyle = "#0a0e17";
        ctx.fillRect(0, 0, w, h);

        const shapes = Object.keys(comparison);
        if (shapes.length === 0) return;

        const metrics = ["drag_coefficient", "lift_coefficient", "drag_force", "lift_force"];
        const metricLabels = {
            drag_coefficient: "阻力系数 Cd",
            lift_coefficient: "升力系数 Cl",
            drag_force: "阻力 (N)",
            lift_force: "升力 (N)"
        };

        const padding = { top: 40, bottom: 60, left: 60, right: 30 };
        const chartW = w - padding.left - padding.right;
        const chartH = h - padding.top - padding.bottom;

        const groupW = chartW / metrics.length;
        const barW = groupW / (shapes.length + 1);

        let maxVal = 0;
        shapes.forEach(s => {
            metrics.forEach(m => {
                const v = Math.abs(comparison[s][m] || 0);
                if (v > maxVal) maxVal = v;
            });
        });
        maxVal = maxVal * 1.2 || 1;

        ctx.font = "12px 'Microsoft YaHei', sans-serif";
        ctx.fillStyle = "#6b7c93";
        ctx.textAlign = "center";

        metrics.forEach((m, mi) => {
            const gx = padding.left + mi * groupW + groupW / 2;
            ctx.fillStyle = "#6b7c93";
            ctx.fillText(metricLabels[m], gx, h - 10);

            shapes.forEach((s, si) => {
                const val = comparison[s][m] || 0;
                const barH = (Math.abs(val) / maxVal) * chartH;
                const bx = padding.left + mi * groupW + (si + 0.5) * barW;
                const by = padding.top + chartH - barH;

                ctx.fillStyle = SHAPE_COLORS[s] || "#ffffff";
                ctx.fillRect(bx, by, barW * 0.8, barH);

                ctx.fillStyle = "#e0e6ed";
                ctx.font = "10px Consolas, monospace";
                ctx.fillText(val.toFixed(3), bx + barW * 0.4, by - 5);
            });
        });

        ctx.strokeStyle = "#2a3a5c";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(padding.left, padding.top);
        ctx.lineTo(padding.left, padding.top + chartH);
        ctx.lineTo(padding.left + chartW, padding.top + chartH);
        ctx.stroke();

        const legendY = 15;
        let legendX = padding.left;
        shapes.forEach(s => {
            ctx.fillStyle = SHAPE_COLORS[s] || "#ffffff";
            ctx.fillRect(legendX, legendY - 8, 12, 12);
            ctx.fillStyle = "#e0e6ed";
            ctx.font = "11px 'Microsoft YaHei', sans-serif";
            ctx.textAlign = "left";
            ctx.fillText(SHAPE_LABELS[s] || s, legendX + 16, legendY + 2);
            legendX += 80;
        });
    }

    function drawCrossEraChart(canvasId, data) {
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

        ctx.fillStyle = "#ffd700";
        ctx.fillText("古代鸣镝", cx - maxR - 20, 30);
        ctx.fillStyle = "#00d4aa";
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

            ctx.fillStyle = "#ffd700";
            const mBarW = (mVal / maxBar) * barMaxW;
            ctx.fillRect(cx - 10 - mBarW, iy + 14, mBarW, 16);
            ctx.textAlign = "right";
            ctx.font = "10px Consolas, monospace";
            ctx.fillText(mVal.toFixed(0), cx - 14 - mBarW, iy + 27);

            ctx.fillStyle = "#00d4aa";
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
            wrapText(ctx, comp.key_insight, cx, insightY, w - 40, 18);
        }

        if (comp.era_gap_years) {
            ctx.fillStyle = "#6b7c93";
            ctx.font = "11px 'Microsoft YaHei', sans-serif";
            ctx.textAlign = "center";
            ctx.fillText(`跨时代跨度: ${comp.era_gap_years} 年`, cx, h - 15);
        }
    }

    function wrapText(ctx, text, x, y, maxWidth, lineHeight) {
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

    function updateShapeComparisonDisplay(data) {
        const el = (id) => document.getElementById(id);
        if (!data || !data.comparison) return;

        const container = el("shape-comparison-details");
        if (!container) return;

        let html = "";
        for (const [shape, result] of Object.entries(data.comparison)) {
            html += `<div style="margin-bottom:8px;padding:6px;background:#1a2338;border-radius:4px;border-left:3px solid ${SHAPE_COLORS[shape] || '#fff'}">`;
            html += `<div style="color:${SHAPE_COLORS[shape] || '#fff'};font-weight:600;font-size:12px">${SHAPE_LABELS[shape] || shape}</div>`;
            html += `<div style="color:#a0aec0;font-size:11px">Cd=${result.drag_coefficient.toFixed(3)} Cl=${result.lift_coefficient.toFixed(3)} 阻力=${result.drag_force.toFixed(3)}N 升力=${result.lift_force.toFixed(3)}N</div>`;
            html += `</div>`;
        }
        container.innerHTML = html;
    }

    function updateCrossEraDisplay(data) {
        const el = (id) => document.getElementById(id);
        if (!data) return;

        const container = el("cross-era-details");
        if (!container) return;

        const m = data.mingdi || {};
        const w = data.modern_whistle || {};
        const c = data.comparison || {};

        let html = `<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">`;
        html += `<div style="padding:8px;background:#1a1408;border-radius:4px;border-left:3px solid #ffd700">`;
        html += `<div style="color:#ffd700;font-weight:600;font-size:12px">古代鸣镝</div>`;
        html += `<div style="color:#a0aec0;font-size:11px">频率: ${m.whistle_frequency?.toFixed(0) || 0} Hz</div>`;
        html += `<div style="color:#a0aec0;font-size:11px">声压级: ${m.sound_pressure_level?.toFixed(1) || 0} dB</div>`;
        html += `<div style="color:#a0aec0;font-size:11px">传播: ${m.propagation_distance?.toFixed(0) || 0} m</div>`;
        html += `</div>`;
        html += `<div style="padding:8px;background:#081a14;border-radius:4px;border-left:3px solid #00d4aa">`;
        html += `<div style="color:#00d4aa;font-weight:600;font-size:12px">现代口哨</div>`;
        html += `<div style="color:#a0aec0;font-size:11px">频率: ${w.whistle_frequency?.toFixed(0) || 0} Hz</div>`;
        html += `<div style="color:#a0aec0;font-size:11px">声压级: ${w.sound_pressure_level?.toFixed(1) || 0} dB</div>`;
        html += `<div style="color:#a0aec0;font-size:11px">传播: ${w.propagation_distance?.toFixed(0) || 0} m</div>`;
        html += `</div>`;
        html += `</div>`;
        html += `<div style="margin-top:8px;padding:6px;background:#1a0a14;border-radius:4px;font-size:11px;color:#ff8c00">${c.key_insight || ""}</div>`;
        container.innerHTML = html;
    }

    return {
        fetchShapeComparison,
        fetchCrossEraComparison,
        drawShapeComparisonChart,
        drawCrossEraChart,
        updateShapeComparisonDisplay,
        updateCrossEraDisplay,
        SHAPE_LABELS,
        SHAPE_COLORS
    };
})();
