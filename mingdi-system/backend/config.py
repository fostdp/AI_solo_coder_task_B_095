import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "鸣镝空气动力学仿真与声学分析系统"
    version: str = "1.0.0"

    influxdb_host: str = os.getenv("INFLUXDB_HOST", "localhost")
    influxdb_port: int = int(os.getenv("INFLUXDB_PORT", "8086"))
    influxdb_token: str = os.getenv("INFLUXDB_TOKEN", "my-token")
    influxdb_org: str = os.getenv("INFLUXDB_ORG", "military-history")
    influxdb_bucket: str = os.getenv("INFLUXDB_BUCKET", "mingdi")

    udp_host: str = os.getenv("UDP_HOST", "0.0.0.0")
    udp_port: int = int(os.getenv("UDP_PORT", "5005"))

    mqtt_host: str = os.getenv("MQTT_HOST", "localhost")
    mqtt_port: int = int(os.getenv("MQTT_PORT", "1883"))
    mqtt_topic_alerts: str = os.getenv("MQTT_TOPIC_ALERTS", "mingdi/alerts")

    redis_host: str = os.getenv("REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
    redis_db: int = int(os.getenv("REDIS_DB", "0"))

    alert_frequency_min: float = 800.0
    alert_frequency_max: float = 2500.0
    alert_range_min: float = 150.0
    alert_spl_min: float = 60.0

    arrow_mass: float = 0.025
    arrow_length: float = 0.85
    arrow_diameter: float = 0.008
    whistle_diameter: float = 0.015
    whistle_length: float = 0.03

    air_density: float = 1.225
    air_viscosity: float = 1.81e-5
    speed_of_sound: float = 343.0

    class Config:
        env_file = ".env"


settings = Settings()
