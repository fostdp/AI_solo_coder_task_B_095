import sys
import os
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.message_bus import MessageBus, CHANNELS, iso_now
from backend.physics.aeroacoustics import AeroAcousticsSimulator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [acoustic] %(levelname)s %(message)s"
)
logger = logging.getLogger("acoustic")


class AcousticAnalyzerService:
    def __init__(self):
        self.bus = MessageBus(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379"))
        )
        self.simulator = AeroAcousticsSimulator()
        self.default_distance = float(os.getenv("ACOUSTIC_OBSERVER_DISTANCE", "1.0"))

    def on_raw_sensor(self, message: dict):
        try:
            sensor = message["sensor"]
            velocity = sensor["velocity"]
            rotation = sensor.get("rotation_speed") or 0.0
            whistle_freq_from_sensor = sensor.get("whistle_frequency") or 0.0

            ac_result = self.simulator.simulate(
                velocity=velocity,
                rotation_speed=rotation,
                distance=self.default_distance
            )

            payload = {
                "processed_at": iso_now(),
                "arrow_id": message["arrow_id"],
                "received_at": message.get("received_at"),
                "sensor": sensor,
                "acoustics": ac_result,
                "observer_distance": self.default_distance,
                "measured_vs_calculated_freq": {
                    "measured": whistle_freq_from_sensor,
                    "calculated": ac_result["whistle_frequency"]
                }
            }
            self.bus.publish(CHANNELS["ACOUSTIC_RESULT"], payload)
            breakdown = ac_result.get("source_breakdown", {})
            logger.info(
                f"Acoustic: v={velocity:.1f} m/s, "
                f"f={ac_result['whistle_frequency']:.0f}Hz, "
                f"SPL={ac_result['sound_pressure_level']:.1f}dB "
                f"(near={breakdown.get('near_field_correction', False)})"
            )
        except Exception as e:
            logger.error(f"Acoustic analysis error: {e}", exc_info=True)

    def start(self):
        self.bus.connect()
        self.bus.subscribe(CHANNELS["RAW_SENSOR_DATA"], self.on_raw_sensor)
        logger.info("Acoustic analyzer service started")
        self.bus.run_loop()

    def stop(self):
        self.bus.close()


if __name__ == "__main__":
    AcousticAnalyzerService().start()
