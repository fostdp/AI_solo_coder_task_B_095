const SHAPE_COMPARATOR = (function () {
    const API_BASE = "http://localhost:8000/api/v2/shapes";

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

    function fetchShapeProfiles() {
        return fetch(`${API_BASE}/profiles`)
            .then(r => r.json())
            .catch(err => {
                console.log("[ShapeComparator] Fetch profiles error:", err);
                return null;
            });
    }

    function compareShapes(velocity, shapes, aoa, rotation, includeRanking = true) {
        const shapesParam = Array.isArray(shapes) ? shapes.join(",") : shapes;
        const params = new URLSearchParams({
            velocity: velocity,
            shapes: shapesParam,
            angle_of_attack: aoa,
            rotation_speed: rotation,
            include_ranking: includeRanking
        });
        return fetch(`${API_BASE}/compare?${params.toString()}`)
            .then(r => r.json())
            .catch(err => {
                console.log("[ShapeComparator] Comparison error:", err);
                return null;
            });
    }

    function getShapeQuality(shapeName) {
        return fetch(`${API_BASE}/quality/${shapeName}`)
            .then(r => r.json())
            .catch(err => {
                console.log("[ShapeComparator] Quality error:", err);
                return null;
            });
    }

    function drawComparisonChart(canvasId, comparison) {
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

    function updateComparisonDisplay(data, containerId = "shape-comparison-details") {
        const container = document.getElementById(containerId);
        if (!container || !data || !data.comparison) return;

        let html = "";
        for (const [shape, result] of Object.entries(data.comparison)) {
            html += `<div style="margin-bottom:8px;padding:6px;background:#1a2338;border-radius:4px;border-left:3px solid ${SHAPE_COLORS[shape] || '#fff'}">`;
            html += `<div style="color:${SHAPE_COLORS[shape] || '#fff'};font-weight:600;font-size:12px">${SHAPE_LABELS[shape] || shape}</div>`;
            html += `<div style="color:#a0aec0;font-size:11px">Cd=${result.drag_coefficient.toFixed(3)} Cl=${result.lift_coefficient.toFixed(3)} 阻力=${result.drag_force.toFixed(3)}N 升力=${result.lift_force.toFixed(3)}N</div>`;
            html += `</div>`;
        }

        if (data.ranking && data.ranking.overall) {
            html += `<div style="margin-top:12px;padding:8px;background:#0a1a14;border-radius:4px;border-left:3px solid #00d4aa">`;
            html += `<div style="color:#00d4aa;font-weight:600;font-size:12px;margin-bottom:4px">综合排名</div>`;
            const ranked = Object.entries(data.ranking.overall).sort((a, b) => a[1] - b[1]);
            ranked.forEach(([shape, score], idx) => {
                html += `<div style="color:#a0aec0;font-size:11px">#${idx + 1} ${SHAPE_LABELS[shape] || shape} (${score.toFixed(2)})</div>`;
            });
            html += `</div>`;
        }

        container.innerHTML = html;
    }

    return {
        fetchShapeProfiles,
        compareShapes,
        getShapeQuality,
        drawComparisonChart,
        updateComparisonDisplay,
        SHAPE_LABELS,
        SHAPE_COLORS
    };
})();
