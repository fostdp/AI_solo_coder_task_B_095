const VOLLEY_PANEL = (function () {
    const API_BASE = "http://localhost:8000/api";

    function fetchVolleyPreset(pattern, count, velocity, rotationSpeed, spacing) {
        return fetch(`${API_BASE}/volley/preset?pattern=${pattern}&count=${count}&velocity=${velocity}&rotation_speed=${rotationSpeed}&spacing=${spacing}`)
            .then(r => r.json())
            .catch(err => {
                console.log("Volley preset error:", err);
                return null;
            });
    }

    function drawVolleyField(canvasId, result) {
        const canvas = document.getElementById(canvasId);
        if (!canvas || !result || !result.field) return;
        const ctx = canvas.getContext("2d");

        const container = canvas.parentElement;
        const w = canvas.width = container.clientWidth || 500;
        const h = canvas.height = 400;

        ctx.fillStyle = "#0a0e17";
        ctx.fillRect(0, 0, w, h);

        const field = result.field;
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
                const color = splColorRGB(t);
                ctx.fillStyle = `rgb(${color.r},${color.g},${color.b})`;
                ctx.fillRect(j * cellW, i * cellH, cellW + 0.5, cellH + 0.5);
            }
        }

        if (result.individual_results) {
            result.individual_results.forEach(arrow => {
                const pos = arrow.position || [0, 0];
                const spacing = result.grid_spacing || 2.0;
                const px = (pos[0] / (spacing * cols / 2) + 1) * w / 2;
                const py = (pos[1] / (spacing * rows / 2) + 1) * h / 2;

                ctx.beginPath();
                ctx.arc(px, py, 5, 0, Math.PI * 2);
                ctx.fillStyle = "#ffd700";
                ctx.fill();
                ctx.strokeStyle = "#0a0e17";
                ctx.lineWidth = 1;
                ctx.stroke();
            });
        }

        drawColorBar(ctx, w - 50, 30, 20, h - 60, minSPL, maxSPL);

        ctx.fillStyle = "#ffd700";
        ctx.font = "bold 13px 'Microsoft YaHei', sans-serif";
        ctx.textAlign = "left";
        ctx.fillText(`齐射声场叠加 (${result.arrow_count || 0}支)`, 10, 20);

        if (result.enhancement_vs_single_db !== undefined) {
            ctx.fillStyle = "#00d4aa";
            ctx.font = "11px 'Microsoft YaHei', sans-serif";
            ctx.fillText(`叠加增强: +${result.enhancement_vs_single_db.toFixed(1)} dB`, 10, h - 10);
        }
    }

    function drawColorBar(ctx, x, y, width, height, minVal, maxVal) {
        for (let i = 0; i < height; i++) {
            const t = 1 - i / height;
            const color = splColorRGB(t);
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

    function splColorRGB(t) {
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

    function updateVolleyInfo(result) {
        const el = (id) => document.getElementById(id);
        if (!result) return;

        const info = el("volley-info");
        if (info) {
            let html = `<div style="font-size:12px;color:#a0aec0">`;
            html += `<div>箭数: <span style="color:#ffd700">${result.arrow_count}</span></div>`;
            html += `<div>观测点SPL: <span style="color:#00d4aa">${result.observer_spl?.toFixed(1) || 0} dB</span></div>`;
            html += `<div>场内峰值: <span style="color:#ff6b6b">${result.peak_spl_in_field?.toFixed(1) || 0} dB</span></div>`;
            html += `<div>叠加增强: <span style="color:#ffd700">+${result.enhancement_vs_single_db?.toFixed(1) || 0} dB</span></div>`;
            if (result.interference_zones) {
                html += `<div style="margin-top:4px">建设性干涉: <span style="color:#00d4aa">${result.interference_zones.constructive_count}</span> 处</div>`;
                html += `<div>破坏性干涉: <span style="color:#ff6b6b">${result.interference_zones.destructive_count}</span> 处</div>`;
            }
            html += `</div>`;
            info.innerHTML = html;
        }
    }

    return {
        fetchVolleyPreset,
        drawVolleyField,
        updateVolleyInfo,
        splColorRGB
    };
})();
