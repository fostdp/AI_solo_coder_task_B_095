import threading
import gzip
import os
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager
from typing import Optional, List
import logging
import math
import os

from .config import settings
from .models import SensorData, FlightStatus, ShapeComparisonRequest, VolleySimulationRequest, LaunchExperienceRequest
from .influx_client import InfluxDBStore
from .message_bus import MessageBus, CHANNELS
from .physics import AeroDynamicsSimulator, AeroAcousticsSimulator, ShapeAwareAeroSimulator, CrossEraAcousticComparator, VolleySimulation, AudioSynthesisParams, SHAPE_PROFILES

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

influx_store: Optional[InfluxDBStore] = None
aero_sim: Optional[AeroDynamicsSimulator] = None
acoustics_sim: Optional[AeroAcousticsSimulator] = None
shape_aero_sim: Optional[ShapeAwareAeroSimulator] = None
cross_era_comparator: Optional[CrossEraAcousticComparator] = None
volley_sim: Optional[VolleySimulation] = None
audio_params: Optional[AudioSynthesisParams] = None
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
    global influx_store, aero_sim, acoustics_sim, shape_aero_sim, cross_era_comparator, volley_sim, audio_params

    logger.info("Starting up MingDi API Gateway...")

    influx_store = InfluxDBStore()
    aero_sim = AeroDynamicsSimulator()
    acoustics_sim = AeroAcousticsSimulator()
    shape_aero_sim = ShapeAwareAeroSimulator()
    cross_era_comparator = CrossEraAcousticComparator()
    volley_sim = VolleySimulation()
    audio_params = AudioSynthesisParams()

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
app.add_middleware(GZipMiddleware, minimum_size=500)

_frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")

class PreCompressedStaticMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        accept_encoding = request.headers.get("accept-encoding", "")
        if path.startswith("/static/") and "gzip" in accept_encoding.lower():
            rel = path[len("/static/"):]
            gz_path = os.path.join(_frontend_path, rel + ".gz")
            orig_path = os.path.join(_frontend_path, rel)
            if os.path.isfile(gz_path) and os.path.isfile(orig_path):
                headers = {
                    "Content-Encoding": "gzip",
                    "Vary": "Accept-Encoding",
                }
                ext = os.path.splitext(rel)[1].lower()
                mime = {
                    ".js": "application/javascript",
                    ".css": "text/css",
                    ".html": "text/html",
                    ".json": "application/json",
                    ".svg": "image/svg+xml",
                }.get(ext)
                if mime:
                    headers["Content-Type"] = mime
                return Response(content=open(gz_path, "rb").read(), headers=headers)
        return await call_next(request)

app.add_middleware(PreCompressedStaticMiddleware)

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


@app.get("/api/shapes/profiles")
async def get_shape_profiles():
    return {"shapes": list(SHAPE_PROFILES.keys()), "profiles": SHAPE_PROFILES}


@app.get("/api/shapes/compare")
async def compare_shapes(
    velocity: float = Query(..., gt=0),
    shapes: str = Query("conical,spherical,blunt,ogival"),
    angle_of_attack: float = Query(0.0),
    rotation_speed: float = Query(0.0)
):
    try:
        shape_list = [s.strip() for s in shapes.split(",") if s.strip()]
        results = shape_aero_sim.compare_shapes(velocity, shape_list, angle_of_attack, rotation_speed)
        return {"velocity": velocity, "angle_of_attack": angle_of_attack, "comparison": results}
    except Exception as e:
        logger.error(f"Error in shape comparison: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/shapes/compare")
async def compare_shapes_post(req: ShapeComparisonRequest):
    try:
        results = shape_aero_sim.compare_shapes(req.velocity, req.shapes, req.angle_of_attack, req.rotation_speed)
        return {"velocity": req.velocity, "angle_of_attack": req.angle_of_attack, "comparison": results}
    except Exception as e:
        logger.error(f"Error in shape comparison: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/acoustics/cross-era-comparison")
async def cross_era_comparison(
    velocity: float = Query(..., gt=0),
    rotation_speed: float = Query(100.0),
    distance: float = Query(1.0),
    modern_whistle_length: float = Query(0.025),
    modern_whistle_diameter: float = Query(0.012)
):
    try:
        result = cross_era_comparator.compare(
            velocity, rotation_speed, distance,
            modern_whistle_length, modern_whistle_diameter
        )
        return result
    except Exception as e:
        logger.error(f"Error in cross-era comparison: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/volley/simulate")
async def simulate_volley(req: VolleySimulationRequest):
    try:
        arrows_data = []
        for a in req.arrows:
            arrows_data.append({
                "arrow_id": a.arrow_id,
                "velocity": a.velocity,
                "rotation_speed": a.rotation_speed,
                "whistle_frequency": a.whistle_frequency,
                "sound_pressure_level": a.sound_pressure_level,
                "position": tuple(a.position),
            })
        result = volley_sim.simulate_volley(
            arrows=arrows_data,
            grid_size=req.grid_size,
            grid_spacing=req.grid_spacing,
            observer_position=tuple(req.observer_position),
        )
        return result
    except Exception as e:
        logger.error(f"Error in volley simulation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/volley/preset")
async def volley_preset(
    pattern: str = Query("line", description="齐射阵型: line, wedge, arc, random"),
    count: int = Query(5, ge=1, le=20),
    velocity: float = Query(65.0, gt=0),
    rotation_speed: float = Query(100.0),
    spacing: float = Query(5.0, gt=0)
):
    try:
        arrows = []
        acoustics_sim_local = AeroAcousticsSimulator()
        ac_result = acoustics_sim_local.simulate(velocity, rotation_speed, 1.0)

        if pattern == "line":
            for i in range(count):
                x = (i - count / 2) * spacing
                arrows.append({
                    "arrow_id": f"volley-{i+1}",
                    "velocity": velocity,
                    "rotation_speed": rotation_speed,
                    "whistle_frequency": ac_result["whistle_frequency"],
                    "sound_pressure_level": ac_result["sound_pressure_level"],
                    "position": (x, 0.0),
                })
        elif pattern == "wedge":
            for i in range(count):
                row = i // 2
                side = 1 if i % 2 == 0 else -1
                x = side * (row + 1) * spacing * 0.5
                y = row * spacing
                arrows.append({
                    "arrow_id": f"volley-{i+1}",
                    "velocity": velocity,
                    "rotation_speed": rotation_speed,
                    "whistle_frequency": ac_result["whistle_frequency"],
                    "sound_pressure_level": ac_result["sound_pressure_level"],
                    "position": (x, y),
                })
        elif pattern == "arc":
            import random
            radius = count * spacing / (2 * math.pi)
            for i in range(count):
                angle = math.pi * (i / max(count - 1, 1) - 0.5)
                x = radius * math.sin(angle)
                y = radius * (1 - math.cos(angle))
                arrows.append({
                    "arrow_id": f"volley-{i+1}",
                    "velocity": velocity + random.uniform(-2, 2),
                    "rotation_speed": rotation_speed,
                    "whistle_frequency": ac_result["whistle_frequency"],
                    "sound_pressure_level": ac_result["sound_pressure_level"],
                    "position": (x, y),
                })
        else:
            import random
            for i in range(count):
                arrows.append({
                    "arrow_id": f"volley-{i+1}",
                    "velocity": velocity + random.uniform(-5, 5),
                    "rotation_speed": rotation_speed + random.uniform(-10, 10),
                    "whistle_frequency": ac_result["whistle_frequency"],
                    "sound_pressure_level": ac_result["sound_pressure_level"],
                    "position": (random.uniform(-count*spacing/2, count*spacing/2), random.uniform(-spacing, spacing)),
                })

        result = volley_sim.simulate_volley(arrows=arrows, grid_size=40, grid_spacing=2.0, observer_position=(0.0, 50.0))
        result["pattern"] = pattern
        return result
    except Exception as e:
        logger.error(f"Error in volley preset: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/launch/audio-params")
async def get_launch_audio_params(
    velocity: float = Query(65.0, gt=0),
    launch_angle: float = Query(0.3),
    rotation_speed: float = Query(100.0),
    shape_profile: str = Query("conical"),
    observer_distance: float = Query(10.0)
):
    try:
        result = audio_params.calculate(
            velocity=velocity,
            rotation_speed=rotation_speed,
            shape_profile=shape_profile,
            distance=observer_distance,
        )
        trajectory = aero_sim.calculate_trajectory(velocity, launch_angle, rotation_speed)

        peak_altitude = max((p["altitude"] for p in trajectory), default=0)
        final_range = trajectory[-1]["x"] if trajectory else 0
        flight_time = trajectory[-1]["time"] if trajectory else 0

        result["trajectory"] = {
            "peak_altitude": round(peak_altitude, 1),
            "estimated_range": round(final_range, 1),
            "flight_time": round(flight_time, 2),
            "point_count": len(trajectory),
        }
        return result
    except Exception as e:
        logger.error(f"Error in launch audio params: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/launch/experience")
async def launch_experience(req: LaunchExperienceRequest):
    try:
        audio = audio_params.calculate(
            velocity=req.velocity,
            rotation_speed=req.rotation_speed,
            shape_profile=req.shape_profile,
            distance=req.observer_distance,
        )
        trajectory = aero_sim.calculate_trajectory(req.velocity, req.launch_angle, req.rotation_speed)

        peak_altitude = max((p["altitude"] for p in trajectory), default=0)
        final_range = trajectory[-1]["x"] if trajectory else 0
        flight_time = trajectory[-1]["time"] if trajectory else 0

        aero_result = shape_aero_sim.simulate_shape(
            req.velocity, req.shape_profile, 0.0, req.rotation_speed
        )
        ac_result = acoustics_sim.simulate(req.velocity, req.rotation_speed, req.observer_distance)

        return {
            "audio": audio,
            "trajectory_summary": {
                "peak_altitude": round(peak_altitude, 1),
                "estimated_range": round(final_range, 1),
                "flight_time": round(flight_time, 2),
                "launch_angle": req.launch_angle,
                "initial_velocity": req.velocity,
            },
            "aerodynamics": aero_result,
            "acoustics": ac_result,
        }
    except Exception as e:
        logger.error(f"Error in launch experience: {e}")
        raise HTTPException(status_code=500, detail=str(e))
