import sys
import os
import logging
import socket
import json
import threading
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.config import settings
from backend.message_bus import MessageBus, CHANNELS, iso_now
from backend.models import SensorData

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [udp_receiver] %(levelname)s %(message)s"
)
logger = logging.getLogger("udp_receiver")


class UDPReceiver:
    def __init__(self):
        self.host = settings.udp_host
        self.port = settings.udp_port
        self.socket: Optional[socket.socket] = None
        self.bus = MessageBus(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379"))
        )
        self.running = False
        self.thread: Optional[threading.Thread] = None

    def validate(self, raw: dict) -> Optional[SensorData]:
        try:
            if "velocity" not in raw:
                logger.warning("Missing velocity field")
                return None
            velocity = float(raw["velocity"])
            if velocity < 0 or velocity > 1000:
                logger.warning(f"Velocity out of range: {velocity}")
                return None
            if "whistle_frequency" in raw:
                f = float(raw["whistle_frequency"])
                if f < 0 or f > 20000:
                    logger.warning(f"Frequency out of range: {f}")
                    raw["whistle_frequency"] = 0
            return SensorData(
                arrow_id=raw.get("arrow_id", "unknown"),
                timestamp=datetime.fromisoformat(raw["timestamp"]) if raw.get("timestamp") else datetime.utcnow(),
                velocity=velocity,
                rotation_speed=float(raw.get("rotation_speed", 0) or 0),
                whistle_frequency=float(raw.get("whistle_frequency", 0) or 0),
                sound_pressure_level=float(raw.get("sound_pressure_level", 0) or 0),
                altitude=float(raw.get("altitude", 0) or 0),
                pitch=float(raw.get("pitch", 0) or 0),
                yaw=float(raw.get("yaw", 0) or 0)
            )
        except (ValueError, KeyError) as e:
            logger.error(f"Data validation failed: {e}")
            return None

    def start(self):
        self.bus.connect()
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((self.host, self.port))
        self.socket.settimeout(1.0)
        self.running = True
        self.thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.thread.start()
        logger.info(f"UDP receiver listening on {self.host}:{self.port}")
        self.thread.join()

    def _listen_loop(self):
        while self.running:
            try:
                data, _ = self.socket.recvfrom(4096)
                raw = json.loads(data.decode("utf-8"))
                validated = self.validate(raw)
                if validated is None:
                    continue
                payload = {
                    "received_at": iso_now(),
                    "arrow_id": validated.arrow_id,
                    "sensor": validated.model_dump(mode="json")
                }
                ok = self.bus.publish(CHANNELS["RAW_SENSOR_DATA"], payload)
                if not ok:
                    logger.warning("Publish to RAW_SENSOR_DATA failed, Redis down?")
            except socket.timeout:
                continue
            except json.JSONDecodeError:
                logger.error("Invalid JSON received")
            except Exception as e:
                if self.running:
                    logger.error(f"UDP error: {e}")

    def stop(self):
        self.running = False
        if self.socket:
            self.socket.close()
        self.bus.close()


if __name__ == "__main__":
    UDPReceiver().start()
