import sys
import os
import logging
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.config import settings
from backend.message_bus import MessageBus, CHANNELS, iso_now
from backend.mqtt_publisher import MQTTPublisher
from backend.influx_client import InfluxDBStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [alarm_mqtt] %(levelname)s %(message)s"
)
logger = logging.getLogger("alarm_mqtt")


class AlarmMQTTService:
    def __init__(self):
        self.bus = MessageBus(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379"))
        )
        self.mqtt = MQTTPublisher()
        self.influx: Optional[InfluxDBStore] = None
        try:
            self.influx = InfluxDBStore()
        except Exception as e:
            logger.warning(f"InfluxDB not available: {e}")
        self._last_alerts = {}
        self._aero_cache = {}
        self._acoustic_cache = {}

    def _dedup(self, arrow_id: str, alert_type: str, ts: datetime) -> bool:
        key = f"{arrow_id}_{alert_type}"
        last = self._last_alerts.get(key)
        if last and (ts - last).total_seconds() < 30:
            return False
        self._last_alerts[key] = ts
        return True

    def _fire_alert(self, alert: dict):
        ts = datetime.fromisoformat(alert["timestamp"])
        if not self._dedup(alert["arrow_id"], alert["alert_type"], ts):
            return
        alert_dict = dict(alert)
        if self.influx:
            try:
                self.influx.write_alert(alert_dict)
            except Exception as e:
                logger.error(f"InfluxDB write alert error: {e}")
        self.mqtt.publish_alert(alert_dict)
        self.bus.publish(CHANNELS["ALERT_TRIGGERED"], {
            "fired_at": iso_now(),
            "alert": alert_dict
        })
        logger.warning(f"ALERT [{alert['severity']}] {alert['arrow_id']}: {alert['message']}")

    def _check_range(self, arrow_id: str, estimated_range: float, ts_iso: str):
        if estimated_range < settings.alert_range_min:
            self._fire_alert({
                "arrow_id": arrow_id,
                "alert_type": "range_insufficient",
                "message": f"预估射程不足: {estimated_range:.1f} m",
                "timestamp": ts_iso,
                "severity": "critical",
                "current_value": estimated_range,
                "threshold": settings.alert_range_min
            })

    def _check_frequency(self, arrow_id: str, freq: float, ts_iso: str):
        if freq <= 0:
            return
        if freq < settings.alert_frequency_min:
            self._fire_alert({
                "arrow_id": arrow_id,
                "alert_type": "frequency_low",
                "message": f"哨音频率过低: {freq:.1f} Hz",
                "timestamp": ts_iso,
                "severity": "warning",
                "current_value": freq,
                "threshold": settings.alert_frequency_min
            })
        elif freq > settings.alert_frequency_max:
            self._fire_alert({
                "arrow_id": arrow_id,
                "alert_type": "frequency_high",
                "message": f"哨音频率过高: {freq:.1f} Hz",
                "timestamp": ts_iso,
                "severity": "warning",
                "current_value": freq,
                "threshold": settings.alert_frequency_max
            })

    def _check_spl(self, arrow_id: str, spl: float, ts_iso: str):
        if spl <= 0:
            return
        if spl < settings.alert_spl_min:
            self._fire_alert({
                "arrow_id": arrow_id,
                "alert_type": "spl_low",
                "message": f"声压级过低: {spl:.1f} dB",
                "timestamp": ts_iso,
                "severity": "warning",
                "current_value": spl,
                "threshold": settings.alert_spl_min
            })

    def on_aero(self, message: dict):
        try:
            arrow_id = message["arrow_id"]
            self._aero_cache[arrow_id] = message
            ts = message.get("received_at") or message["processed_at"]
            self._check_range(arrow_id, message["estimated_range"], ts)
            self._try_aggregate(arrow_id)
        except Exception as e:
            logger.error(f"Aero alarm error: {e}")

    def on_acoustic(self, message: dict):
        try:
            arrow_id = message["arrow_id"]
            self._acoustic_cache[arrow_id] = message
            ts = message.get("received_at") or message["processed_at"]
            acoustic = message["acoustics"]
            self._check_frequency(arrow_id, acoustic["whistle_frequency"], ts)
            self._check_spl(arrow_id, acoustic["sound_pressure_level"], ts)
            self._try_aggregate(arrow_id)
        except Exception as e:
            logger.error(f"Acoustic alarm error: {e}")

    def _try_aggregate(self, arrow_id: str):
        aero = self._aero_cache.get(arrow_id)
        acoustic = self._acoustic_cache.get(arrow_id)
        if not (aero and acoustic):
            return
        if aero.get("received_at") != acoustic.get("received_at"):
            return
        payload = {
            "aggregated_at": iso_now(),
            "arrow_id": arrow_id,
            "sensor": aero["sensor"],
            "aerodynamics": aero["aerodynamics"],
            "estimated_range": aero["estimated_range"],
            "acoustics": acoustic["acoustics"]
        }
        self.bus.publish(CHANNELS["AGGREGATED_DATA"], payload)

    def start(self):
        self.bus.connect()
        self.mqtt.connect()
        self.bus.subscribe(CHANNELS["AERO_RESULT"], self.on_aero)
        self.bus.subscribe(CHANNELS["ACOUSTIC_RESULT"], self.on_acoustic)
        logger.info("Alarm MQTT service started")
        self.bus.run_loop()

    def stop(self):
        self.bus.close()
        self.mqtt.disconnect()
        if self.influx:
            self.influx.close()


if __name__ == "__main__":
    AlarmMQTTService().start()
