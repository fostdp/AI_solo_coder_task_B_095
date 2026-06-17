import threading
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from typing import Optional, List
import logging
import math
import os

from .config import settings
from .models import SensorData, FlightStatus
from .influx_client import InfluxDBStore
from .message_bus import MessageBus, CHANNELS
from .physics import AeroDynamicsSimulator, AeroAcousticsSimulator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

influx_store: Optional[InfluxDBStore] = None
aero_sim: Optional[AeroDynamicsSimulator] = None
acoustics_sim: Optional[AeroAcousticsSimulator] = None
message_bus: Optional[MessageBus] = None
_latest_aggregated = {}
_ws_clients: List[WebSocket] = []
_ws_lock = threading.Lock()


def _on_aggregated(message: dict):
    arrow_id = message["arrow_id"]
    _latest_aggregated[arrow_id] = message
    snapshot = {
        "arrow_id": arrow_id,
        "sensor": message.get("sensor"),
        "aerodynamics": message.get("aerodynamics"),
        "acoustics": message.get("acoustics"),
        "estimated_range": message.get("estimated_range"),
        "aggregated_at": message.get("aggregated_at")
    }
    with _ws_lock:
        dead = []
        for ws in _ws_clients:
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                loop.run_until_complete(ws.send_json(snapshot))
                loop.close()
            except Exception:
                dead.append(ws)
        for d in dead:
            _ws_clients.remove(d)


def _start_bus_thread():
    global message_bus
    message_bus = MessageBus(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", "6379"))
    )
    message_bus.connect()
    message_bus.subscribe(CHANNELS["AGGREGATED_DATA"], _on_aggregated)
    logger.info("FastAPI message bus subscribed to AGGREGATED_DATA")
    message_bus.run_loop()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global influx_store, aero_sim, acoustics_sim

    logger.info("Starting up MingDi API Gateway...")

    influx_store = InfluxDBStore()
    aero_sim = AeroDynamicsSimulator()
    acoustics_sim = AeroAcousticsSimulator()

    bus_thread = threading.Thread(target=_start_bus_thread, daemon=True)
    bus_thread.start()

    logger.info("MingDi API Gateway started")

    yield

    logger.info("Shutting down MingDi API Gateway...")
    if message_bus:
        message_bus.close()
    if influx_store:
        influx_store.close()
    logger.info("MingDi API Gateway shutdown complete")


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")


@app.get("/")
async def root():
    return {
        "name": settings.app_name,
        "version": settings.version,
        "architecture": "microservices",
        "message_bus": "Redis Pub/Sub",
        "status": "running"
    }


@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "gateway": True,
        "redis_connected": message_bus.client is not None if message_bus else False,
        "influx_connected": influx_store is not None,
        "latest_arrow_count": len(_latest_aggregated)
    }


@app.get("/api/config")
async def get_config():
    return {
        "arrow": {
            "mass": settings.arrow_mass,
            "length": settings.arrow_length,
            "diameter": settings.arrow_diameter,
            "whistle_diameter": settings.whistle_d,
            "whistle_length": settings.whistle_l
        },
        "air": {
            "density": settings.air_density,
            "viscosity": settings.air_viscosity,
            "speed_of_sound": settings.speed_of_sound
        },
        "alerts": {
            "frequency_min": settings.alert_frequency_min,
            "frequency_max": settings.alert_frequency_max,
            "range_min": settings.alert_range_min,
            "spl_min": settings.alert_spl_min
        }
    }


@app.post("/api/sensor/data")
async def receive_sensor_data(data: SensorData):
    if not message_bus:
        raise HTTPException(status_code=503, detail="Message bus unavailable")
    payload = {
        "received_at": data.timestamp.isoformat() if data.timestamp else None,
        "arrow_id": data.arrow_id,
        "sensor": data.model_dump(mode="json")
    }
    ok = message_bus.publish(CHANNELS["RAW_SENSOR_DATA"], payload)
    if not ok:
        raise HTTPException(status_code=503, detail="Failed to publish")
    return {"status": "published", "channel": CHANNELS["RAW_SENSOR_DATA"]}


@app.get("/api/sensor/data")
async def get_sensor_data(
    arrow_id: Optional[str] = Query(None),
    start: str = Query("-1h"),
    limit: int = Query(100)
):
    try:
        data = influx_store.query_sensor_data(arrow_id=arrow_id, start=start, limit=limit)
        return {"count": len(data), "data": data}
    except Exception as e:
        logger.error(f"Error querying sensor data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/arrow/{arrow_id}/status")
async def get_arrow_status(arrow_id: str):
    try:
        if arrow_id in _latest_aggregated:
            agg = _latest_aggregated[arrow_id]
            sens = agg.get("sensor") or {}
            aero = agg.get("aerodynamics") or {}
            ac = agg.get("acoustics") or {}
            is_alert = False
            if aero:
                estimated_range = agg.get("estimated_range", 0)
                if estimated_range < settings.alert_range_min:
                    is_alert = True
            if ac:
                if (ac.get("whistle_frequency", 0) < settings.alert_frequency_min
                        or ac.get("whistle_frequency", 0) > settings.alert_frequency_max
                        or ac.get("sound_pressure_level", 0) < settings.alert_spl_min):
                    is_alert = True
            return {
                "arrow_id": arrow_id,
                "timestamp": sens.get("timestamp"),
                "velocity": sens.get("velocity"),
                "rotation_speed": sens.get("rotation_speed"),
                "altitude": sens.get("altitude"),
                "whistle_frequency": ac.get("whistle_frequency"),
                "sound_pressure_level": ac.get("sound_pressure_level"),
                "estimated_range": agg.get("estimated_range"),
                "is_alert": is_alert
            }
        latest = influx_store.query_latest_status(arrow_id)
        if not latest:
            raise HTTPException(status_code=404, detail=f"Arrow {arrow_id} not found")
        estimated_range = aero_sim.estimate_range(
            latest["velocity"],
            latest.get("pitch", 0.3)
        )
        status = FlightStatus(
            arrow_id=arrow_id,
            timestamp=latest["timestamp"],
            velocity=latest["velocity"],
            rotation_speed=latest["rotation_speed"],
            altitude=latest.get("altitude", 0),
            whistle_frequency=latest["whistle_frequency"],
            sound_pressure_level=latest["sound_pressure_level"],
            estimated_range=estimated_range,
            is_alert=(
                latest["whistle_frequency"] < settings.alert_frequency_min
                or latest["whistle_frequency"] > settings.alert_frequency_max
                or estimated_range < settings.alert_range_min
                or latest["sound_pressure_level"] < settings.alert_spl_min
            )
        )
        return status.model_dump()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting arrow status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/aerodynamics/simulate")
async def simulate_aerodynamics(
    velocity: float = Query(..., gt=0),
    angle_of_attack: float = Query(0.0),
    rotation_speed: float = Query(0.0)
):
    try:
        result = aero_sim.simulate(velocity, angle_of_attack, rotation_speed)
        return result
    except Exception as e:
        logger.error(f"Error in aerodynamics simulation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/aerodynamics/trajectory")
async def simulate_trajectory(
    initial_velocity: float = Query(..., gt=0),
    launch_angle: float = Query(0.3),
    initial_rotation: float = Query(0.0)
):
    try:
        trajectory = aero_sim.calculate_trajectory(
            initial_velocity, launch_angle, initial_rotation
        )
        return {"points": len(trajectory), "trajectory": trajectory}
    except Exception as e:
        logger.error(f"Error in trajectory simulation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/acoustics/simulate")
async def simulate_acoustics(
    velocity: float = Query(..., gt=0),
    rotation_speed: float = Query(0.0),
    distance: float = Query(1.0)
):
    try:
        result = acoustics_sim.simulate(velocity, rotation_speed, distance)
        return result
    except Exception as e:
        logger.error(f"Error in acoustics simulation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/acoustics/sound-field")
async def get_sound_field(
    velocity: float = Query(..., gt=0),
    rotation_speed: float = Query(0.0),
    grid_size: int = Query(30),
    grid_spacing: float = Query(1.0)
):
    try:
        field = acoustics_sim.calculate_sound_field(
            source_position=(0, 0),
            velocity=velocity,
            rotation_speed=rotation_speed,
            grid_size=grid_size,
            grid_spacing=grid_spacing
        )
        return {"grid_size": grid_size, "grid_spacing": grid_spacing, "field": field}
    except Exception as e:
        logger.error(f"Error calculating sound field: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/alerts")
async def get_alerts(
    arrow_id: Optional[str] = Query(None),
    start: str = Query("-24h"),
    limit: int = Query(50)
):
    try:
        alerts = influx_store.query_alerts(arrow_id=arrow_id, start=start, limit=limit)
        return {"count": len(alerts), "alerts": alerts}
    except Exception as e:
        logger.error(f"Error querying alerts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws/stream")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    with _ws_lock:
        _ws_clients.append(websocket)
    try:
        for arrow_id, data in _latest_aggregated.items():
            await websocket.send_json({
                "arrow_id": arrow_id,
                "sensor": data.get("sensor"),
                "aerodynamics": data.get("aerodynamics"),
                "acoustics": data.get("acoustics"),
                "estimated_range": data.get("estimated_range")
            })
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        with _ws_lock:
            if websocket in _ws_clients:
                _ws_clients.remove(websocket)


@app.get("/api/flow-streamlines")
async def get_flow_streamlines(
    velocity: float = Query(50.0),
    grid_size: int = Query(20)
):
    try:
        streamlines = []
        for i in range(grid_size):
            streamline = []
            y_start = -5 + (10 * i / (grid_size - 1))
            x, y = -10.0, y_start
            for step in range(50):
                speed_factor = 1.0 - 0.3 * math.exp(-(y ** 2 / 2))
                vx = velocity * speed_factor
                vy = 0.05 * velocity * math.sin(x * 0.1)
                x += vx * 0.1
                y += vy * 0.1
                if x > 15:
                    break
                streamline.append({"x": round(x, 3), "y": round(y, 3)})
            streamlines.append(streamline)
        return {"streamlines": streamlines, "velocity": velocity}
    except Exception as e:
        logger.error(f"Error generating streamlines: {e}")
        raise HTTPException(status_code=500, detail=str(e))
