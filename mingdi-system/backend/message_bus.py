import json
import logging
from datetime import datetime
from typing import Callable, Optional
import redis

logger = logging.getLogger(__name__)

CHANNELS = {
    "RAW_SENSOR_DATA": "mingdi:raw_sensor_data",
    "AERO_RESULT": "mingdi:aero_result",
    "ACOUSTIC_RESULT": "mingdi:acoustic_result",
    "AGGREGATED_DATA": "mingdi:aggregated_data",
    "ALERT_TRIGGERED": "mingdi:alert_triggered"
}


def iso_now() -> str:
    return datetime.utcnow().isoformat()


class MessageBus:
    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0):
        self.host = host
        self.port = port
        self.db = db
        self.client: Optional[redis.Redis] = None
        self._pubsub: Optional[redis.client.PubSub] = None
        self._handlers = {}

    def connect(self):
        try:
            self.client = redis.Redis(
                host=self.host, port=self.port, db=self.db,
                decode_responses=True, socket_connect_timeout=3
            )
            self.client.ping()
            self._pubsub = self.client.pubsub(ignore_subscribe_messages=True)
            logger.info(f"Redis connected: {self.host}:{self.port}")
        except redis.exceptions.RedisError as e:
            logger.error(f"Redis connection failed: {e}")
            self.client = None

    def publish(self, channel: str, payload: dict) -> bool:
        if not self.client:
            return False
        try:
            message = json.dumps(payload, default=str)
            self.client.publish(channel, message)
            return True
        except (redis.exceptions.RedisError, TypeError) as e:
            logger.error(f"Publish failed on {channel}: {e}")
            return False

    def subscribe(self, channel: str, handler: Callable[[dict], None]):
        if not self._pubsub:
            return False
        self._handlers[channel] = handler
        self._pubsub.subscribe(**{channel: self._wrap_handler(handler)})
        logger.info(f"Subscribed to channel: {channel}")
        return True

    def _wrap_handler(self, handler: Callable[[dict], None]) -> Callable:
        def _inner(message):
            try:
                data = json.loads(message["data"])
                handler(data)
            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"Invalid message on channel: {e}")
        return _inner

    def run_loop(self):
        if not self._pubsub:
            return
        for _ in self._pubsub.listen():
            pass

    def close(self):
        if self._pubsub:
            try:
                self._pubsub.close()
            except Exception:
                pass
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
