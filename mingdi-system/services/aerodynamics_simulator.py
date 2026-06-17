import sys
import os
import logging
import threading

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.message_bus import MessageBus, CHANNELS, iso_now
from backend.physics.aerodynamics import AeroDynamicsSimulator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [aero_sim] %(levelname)s %(message)s"
)
logger = logging.getLogger("aero_sim")


class AerodynamicsSimulatorService:
    def __init__(self):
        self.bus = MessageBus(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379"))
        )
        self.simulator = AeroDynamicsSimulator()

    def on_raw_sensor(self, message: dict):
        try:
            sensor = message["sensor"]
            velocity = sensor["velocity"]
            aoa = sensor.get("pitch") or 0.0
            rotation = sensor.get("rotation_speed") or 0.0

            aero_result = self.simulator.simulate(
                velocity=velocity,
                angle_of_attack=aoa,
                rotation_speed=rotation
            )

            estimated_range = self.simulator.estimate_range(
                velocity, aoa if aoa > 0 else 0.3
            )

            payload = {
                "processed_at": iso_now(),
                "arrow_id": message["arrow_id"],
                "received_at": message.get("received_at"),
                "sensor": sensor,
                "aerodynamics": aero_result,
                "estimated_range": estimated_range
            }
            self.bus.publish(CHANNELS["AERO_RESULT"], payload)
            logger.info(
                f"Aero sim: v={velocity:.1f} m/s, "
                f"Cd={aero_result['drag_coefficient']:.3f}, "
                f"Ma={aero_result['mach_number']:.3f}, "
                f"range≈{estimated_range:.0f}m"
            )
        except Exception as e:
            logger.error(f"Aero simulation error: {e}", exc_info=True)

    def start(self):
        self.bus.connect()
        self.bus.subscribe(CHANNELS["RAW_SENSOR_DATA"], self.on_raw_sensor)
        logger.info("Aerodynamics simulator service started")
        self.bus.run_loop()

    def stop(self):
        self.bus.close()


if __name__ == "__main__":
    AerodynamicsSimulatorService().start()
