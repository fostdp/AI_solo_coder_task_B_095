const ACOUSTIC_PANEL = (function () {
    function splColorInt(t) {
        let r, g, b;
        if (t < 0.25) {
            r = 0; g = 25; b = 80 + t * 680;
        } else if (t < 0.5) {
            const tt = (t - 0.25) / 0.25;
            r = 0; g = 50 + tt * 150; b = 150 - tt * 75;
        } else if (t < 0.75) {
            const tt = (t - 0.5) / 0.25;
            r = tt * 255; g = 200 - tt * 75; b = 75 - tt * 50;
        } else {
            const tt = (t - 0.75) / 0.25;
            r = 255; g = 125 - tt * 100; b = 25 - tt * 25;
        }
        return { r: Math.round(r), g: Math.round(g), b: Math.round(b) };
    }

    function drawSoundFieldCanvas(canvasId, spl) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const w = canvas.width = 240;
        const h = canvas.height = 180;

        ctx.fillStyle = '#0a0e17';
        ctx.fillRect(0, 0, w, h);

        const centerX = w / 2;
        const centerY = h / 2;
        const maxR = Math.min(w, h) * 0.45;

        for (let r = maxR; r > 0; r -= 1) {
            const distRatio = r / maxR;
            const dist = distRatio * 10;
            const localSpl = spl - 20 * Math.log10(Math.max(dist, 0.1));
            const t = Math.max(0, Math.min(1, (localSpl - 40) / 60));
            const c = splColorInt(t);
            ctx.beginPath();
            ctx.arc(centerX, centerY, r, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(${c.r}, ${c.g}, ${c.b}, 0.6)`;
            ctx.fill();
        }

        ctx.fillStyle = '#ffd700';
        ctx.beginPath();
        ctx.arc(centerX, centerY, 4, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = '#ffd700';
        ctx.font = '10px Consolas, monospace';
        ctx.fillText(`${spl.toFixed(0)} dB`, centerX + 10, centerY - 10);

        ctx.strokeStyle = '#2a3a5c';
        ctx.lineWidth = 1;
        ctx.setLineDash([2, 2]);
        ctx.beginPath();
        ctx.arc(centerX, centerY, maxR * 0.5, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
    }

    function updateAcousticsDisplay(data) {
        const el = (id) => document.getElementById(id);
        if (!el('whistle-freq')) return;

        el('whistle-freq').textContent = data.whistle_frequency.toFixed(1);
        el('spl').textContent = data.sound_pressure_level.toFixed(1);
        el('prop-distance').textContent = (data.propagation_distance || 0).toFixed(1);
        el('strouhal').textContent = (data.strouhal_number || 0.2).toFixed(3);

        const splPercent = Math.min(100, Math.max(0, (data.sound_pressure_level - 40) / 80 * 100));
        const splBar = el('spl-bar');
        if (splBar) splBar.style.width = splPercent + '%';
    }

    function updateAlertsList(alerts) {
        const container = document.getElementById('alerts-list');
        if (!container) return;

        if (alerts.length === 0) {
            container.innerHTML = '<div style="color: #4a5568; font-size: 12px; text-align: center; padding: 20px 0;">暂无告警</div>';
            return;
        }

        const labels = {
            'frequency_low': '哨音频率偏低',
            'frequency_high': '哨音频率偏高',
            'range_insufficient': '射程不足',
            'spl_low': '声压级偏低'
        };

        container.innerHTML = alerts.map(alert => `
            <div class="alert-item ${alert.severity === 'critical' ? 'critical' : 'warning'}">
                <div class="alert-type">${labels[alert.alert_type] || alert.alert_type}</div>
                <div class="alert-msg">${alert.message}</div>
                <div class="alert-time">${formatTime(alert.timestamp)}</div>
            </div>
        `).join('');
    }

    function formatTime(isoString) {
        try {
            const date = new Date(isoString);
            return date.toLocaleTimeString('zh-CN');
        } catch {
            return isoString;
        }
    }

    return {
        drawSoundFieldCanvas,
        updateAcousticsDisplay,
        updateAlertsList,
        formatTime
    };
})();
