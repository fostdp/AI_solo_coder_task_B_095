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
from .physics import AeroDynamicsSimulator, AeroAcousticsSimulator, ShapeAwareAeroSimulator, CrossEraAcousticComparator, VolleySimulation, AudioSynthesisParams, SHAPE_PROFILES, BinauralSpatialAudio, get_shape_data_quality, VolleyArrowConfig
from .config_loader import list_modern_whistle_models

from .modules import ShapeComparator, EraComparator, FieldSuperposer, VRWhistlingArrow, CFDWorker, CFDJobStatus

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

shape_comparator: Optional[ShapeComparator] = None
era_comparator: Optional[EraComparator] = None
field_superposer: Optional[FieldSuperposer] = None
vr_whistling_arrow: Optional[VRWhistlingArrow] = None
cfd_worker: Optional[CFDWorker] = None


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
    global shape_comparator, era_comparator, field_superposer, vr_whistling_arrow, cfd_worker

    logger.info("Starting up MingDi API Gateway...")

    influx_store = InfluxDBStore()
    aero_sim = AeroDynamicsSimulator()
    acoustics_sim = AeroAcousticsSimulator()
    shape_aero_sim = ShapeAwareAeroSimulator()
    cross_era_comparator = CrossEraAcousticComparator()
    volley_sim = VolleySimulation()
    audio_params = None

    shape_comparator = ShapeComparator()
    era_comparator = EraComparator()
    field_superposer = FieldSuperposer(backend="auto")
    vr_whistling_arrow = VRWhistlingArrow()
    cfd_worker = CFDWorker(pool_size=2)
    cfd_worker.start()

    bus_thread = threading.Thread(target=_start_bus_thread, daemon=True)
    bus_thread.start()

    logger.info("MingDi API Gateway started: v1 (legacy) + v2 (modular) APIs active")

    yield

    logger.info("Shutting down MingDi API Gateway...")
    if message_bus:
        message_bus.close()
    if influx_store:
        influx_store.close()
    if cfd_worker:
        cfd_worker.stop(wait=False)
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


# ============================================================
# Root & Health
# ============================================================

@app.get("/")
async def root():
    return {
        "name": settings.app_name,
        "version": settings.version,
        "architecture": "microservices + modular",
        "message_bus": "Redis Pub/Sub",
        "modules": ["shape_comparator", "era_comparator", "field_superposer", "vr_whistling_arrow", "cfd_worker"],
        "api_versions": {
            "v1": "/api/* (legacy, backward-compatible)",
            "v2": "/api/v2/* (new modular)"
        },
        "status": "running"
    }


@app.get("/api/health")
async def health_check():
    cfd_stats = cfd_worker.get_stats() if cfd_worker else None
    return {
        "status": "healthy",
        "gateway": True,
        "redis_connected": message_bus.client is not None if message_bus else False,
        "influx_connected": influx_store is not None,
        "latest_arrow_count": len(_latest_aggregated),
        "modules": {
            "shape_comparator": shape_comparator is not None,
            "era_comparator": era_comparator is not None,
            "field_superposer": field_superposer is not None,
            "vr_whistling_arrow": vr_whistling_arrow is not None,
            "cfd_worker": cfd_stats,
        }
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


# ============================================================
# Legacy v1 APIs (unchanged for backward compatibility)
# ============================================================

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


# ============================================================
# Legacy v1 APIs (feature endpoints, unchanged)
# ============================================================

@app.get("/api/shapes/profiles")
async def get_shape_profiles():
    shape_quality = {s: get_shape_data_quality(s) for s in SHAPE_PROFILES}
    return {"shapes": list(SHAPE_PROFILES.keys()),
            "profiles": SHAPE_PROFILES,
            "data_quality": shape_quality,
            "provenance_scale": ["windtunnel (实验测定)", "archaeology (考古实物)", "literature (文献)", "fallback (理论推断)"]}


@app.get("/api/acoustics/modern-whistle-models")
async def get_modern_whistle_models():
    return {"default_model": "fox40_classic",
            "models": list_modern_whistle_models(),
            "certifications": ["FIFA", "FIBA", "FINA", "IOC", "NCAA"]}


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
    modern_model: str = Query("fox40_classic", description="现代口哨标准型号，如 fox40_classic / acme_thunderer_58 / molten_dolfin / fox40_mini"),
    modern_whistle_length: float = Query(None, description="手动覆盖现代口哨长度m，None时使用型号标准值"),
    modern_whistle_diameter: float = Query(None, description="手动覆盖现代口哨直径m，None时使用型号标准值")
):
    try:
        result = cross_era_comparator.compare(
            velocity=velocity,
            rotation_speed=rotation_speed,
            distance=distance,
            modern_model=modern_model,
            modern_whistle_length=modern_whistle_length,
            modern_whistle_diameter=modern_whistle_diameter,
        )
        return result
    except Exception as e:
        logger.error(f"Error in cross-era comparison: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/volley/simulate")
async def simulate_volley(req: VolleySimulationRequest):
    try:
        backend = getattr(req, "backend", "numpy") or "numpy"
        sim = VolleySimulation(backend=backend)
        new_arrows = []
        for a in req.arrows:
            pos = list(a.position) if a.position else [0, 0]
            if len(pos) < 2:
                pos = pos + [0] * (2 - len(pos))
            x, y = float(pos[0]), float(pos[1])
            z = 1.6
            if len(pos) >= 3:
                z = float(pos[2])
            aid = a.arrow_id if hasattr(a, "arrow_id") else f"v-{id(a)}"
            try:
                id_int = int(str(aid).split("-")[-1]) if hasattr(a, "arrow_id") else len(new_arrows) + 1
            except Exception:
                id_int = len(new_arrows) + 1
            new_arrows.append(VolleyArrowConfig(
                id=id_int,
                x=x, y=y, z=z,
                velocity=a.velocity,
                rotation_speed=a.rotation_speed,
                shape_profile=getattr(a, "shape_profile", "conical") or "conical",
                spl_1m=a.sound_pressure_level,
                frequency=a.whistle_frequency,
            ))
        gs = int(req.grid_size)
        extent = float(req.grid_spacing) * float(gs)
        obs = list(req.observer_position) if req.observer_position else [0.0, 0.0, 1.5]
        while len(obs) < 3:
            obs.append(1.5 if len(obs) == 2 else 0.0)
        result = sim.simulate_volley(
            arrows=new_arrows,
            grid_size=gs,
            grid_extent=extent,
            observer_height=float(obs[2]),
            interference_threshold_db=3.0,
        )
        observer_heading_deg = 0.0
        audio = sim.get_audio_synthesis_params(
            volley_result=result,
            listener_position=(float(obs[0]), float(obs[1]), float(obs[2])),
            listener_heading_deg=observer_heading_deg,
            duration_sec=2.5,
        )
        source_position = result.get("sound_centroid_m")
        if source_position and len(source_position) >= 2:
            sp = (source_position[0], source_position[1], float(obs[2]))
        else:
            sp = (float(obs[0]) + 5.0, float(obs[1]), float(obs[2]))
        result["audio_synthesis"] = audio.calculate(
            binaural=True,
            source_position=sp,
            observer_heading_deg=observer_heading_deg,
        )
        return result
    except Exception as e:
        logger.error(f"Error in volley simulation: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/volley/preset")
async def volley_preset(
    pattern: str = Query("line", description="齐射阵型: line, wedge, arc, random, marching_10, ambush_20, scouts_3, single"),
    count: int = Query(5, ge=1, le=20),
    velocity: float = Query(65.0, gt=0),
    rotation_speed: float = Query(100.0),
    spacing: float = Query(5.0, gt=0),
    backend: str = Query("numpy", description="加速后端: numpy / cupy / auto"),
):
    try:
        from .physics.volley_simulation import create_preset_volley
        sim = VolleySimulation(backend=backend)
        presets_known = ("marching_10", "ambush_20", "scouts_3", "single")
        if pattern in presets_known:
            preset_arrows = create_preset_volley(pattern)
            for a in preset_arrows:
                a.velocity = velocity
                a.rotation_speed = rotation_speed
            result = sim.simulate_volley(arrows=preset_arrows)
            result["pattern"] = pattern
            audio = sim.get_audio_synthesis_params(volley_result=result, listener_position=(0, 0, 1.5))
            result["audio_synthesis"] = audio.calculate(binaural=True, source_position=(10, 0, 1.5))
            return result

        acoustics_sim_local = AeroAcousticsSimulator()
        ac_result = acoustics_sim_local.simulate(velocity, rotation_speed, 1.0)
        preset_arrows = []
        shape_cycle = ["conical", "spherical", "blunt", "ogival"]

        if pattern == "line":
            for i in range(count):
                x = (i - count / 2) * spacing
                preset_arrows.append(VolleyArrowConfig(
                    id=i + 1, x=x, y=0.0, z=1.5,
                    velocity=velocity, rotation_speed=rotation_speed,
                    shape_profile=shape_cycle[i % 4],
                    spl_1m=ac_result["sound_pressure_level"],
                    frequency=ac_result["whistle_frequency"],
                ))
        elif pattern == "wedge":
            for i in range(count):
                row = i // 2
                side = 1 if i % 2 == 0 else -1
                x = side * (row + 1) * spacing * 0.5
                y = row * spacing
                preset_arrows.append(VolleyArrowConfig(
                    id=i + 1, x=x, y=y, z=1.5,
                    velocity=velocity, rotation_speed=rotation_speed,
                    shape_profile=shape_cycle[i % 4],
                    spl_1m=ac_result["sound_pressure_level"],
                    frequency=ac_result["whistle_frequency"],
                ))
        elif pattern == "arc":
            import random
            radius = max(count * spacing / (2 * math.pi), spacing)
            for i in range(count):
                angle = math.pi * (i / max(count - 1, 1) - 0.5)
                x = radius * math.sin(angle)
                y = radius * (1 - math.cos(angle))
                preset_arrows.append(VolleyArrowConfig(
                    id=i + 1, x=round(x, 2), y=round(y, 2), z=1.6,
                    velocity=velocity + random.uniform(-2, 2),
                    rotation_speed=rotation_speed,
                    shape_profile=shape_cycle[i % 4],
                    spl_1m=ac_result["sound_pressure_level"],
                    frequency=ac_result["whistle_frequency"],
                ))
        else:
            import random
            for i in range(count):
                preset_arrows.append(VolleyArrowConfig(
                    id=i + 1,
                    x=round(random.uniform(-count * spacing / 2, count * spacing / 2), 2),
                    y=round(random.uniform(-spacing, spacing), 2),
                    z=1.5,
                    velocity=velocity + random.uniform(-5, 5),
                    rotation_speed=rotation_speed + random.uniform(-10, 10),
                    shape_profile=shape_cycle[i % 4],
                    spl_1m=ac_result["sound_pressure_level"],
                    frequency=ac_result["whistle_frequency"],
                ))
        result = sim.simulate_volley(arrows=preset_arrows)
        result["pattern"] = pattern
        audio = sim.get_audio_synthesis_params(volley_result=result, listener_position=(0, 0, 1.5))
        result["audio_synthesis"] = audio.calculate(binaural=True, source_position=(10, 0, 1.5))
        return result
    except Exception as e:
        logger.error(f"Error in volley preset: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


def _build_launch_audio(velocity, rotation_speed, shape_profile, distance, source_position=(10, 0, 1.5),
                       observer_heading_deg=0.0, duration_sec=2.5):
    acoustics_sim_local = AeroAcousticsSimulator()
    ac = acoustics_sim_local.simulate(velocity, rotation_speed, distance)
    waveform = "sawtooth"
    from .physics.volley_simulation import _WAVETABLE_HARMONIC_RATIOS, _WAVETABLE_HARMONIC_GAINS, _SHAPE_TIMBRE
    vib_hz = 5.0 + 0.02 * max(20, min(300, 0.8 * velocity + 40))
    vib_depth = min(1.2, 0.15 + 0.004 * max(20, min(300, 0.8 * velocity + 40)))
    attack = 0.008
    decay = 0.22
    sustain = -12
    release = 0.35
    max_spl = 105.0
    vol_raw = 10 ** ((ac["sound_pressure_level"] - max_spl) / 20)
    vol = max(0.0, min(1.0, vol_raw * 1.5))
    asp = AudioSynthesisParams(
        waveform_type=waveform,
        dominant_frequency=ac["whistle_frequency"],
        harmonic_ratios=list(_WAVETABLE_HARMONIC_RATIOS),
        harmonic_gains=list(_WAVETABLE_HARMONIC_GAINS),
        attack_sec=attack,
        decay_sec=decay,
        sustain_db=sustain,
        release_sec=release,
        vibrato_hz=vib_hz,
        vibrato_depth_semitones=vib_depth,
        total_duration_sec=duration_sec,
        volume=vol,
        timbre_description=_SHAPE_TIMBRE.get(shape_profile, "generic whistle"),
        spl_reference_db=round(ac["sound_pressure_level"], 1),
    )
    return asp.calculate(
        binaural=True,
        source_position=source_position,
        observer_heading_deg=observer_heading_deg,
    )


@app.get("/api/launch/audio-params")
async def get_launch_audio_params(
    velocity: float = Query(65.0, gt=0),
    launch_angle: float = Query(0.3),
    rotation_speed: float = Query(100.0),
    shape_profile: str = Query("conical"),
    observer_distance: float = Query(10.0),
    observer_heading_deg: float = Query(0.0, description="观测者朝向角度(°)，0为朝前方")
):
    try:
        trajectory = aero_sim.calculate_trajectory(velocity, launch_angle, rotation_speed)

        peak_altitude = max((p["altitude"] for p in trajectory), default=0)
        final_range = trajectory[-1]["x"] if trajectory else 0
        flight_time = trajectory[-1]["time"] if trajectory else 0

        source_position = (observer_distance * math.cos(math.radians(-observer_heading_deg)),
                           observer_distance * math.sin(math.radians(-observer_heading_deg)),
                           peak_altitude * 0.3 + 1.5)

        audio = _build_launch_audio(
            velocity=velocity,
            rotation_speed=rotation_speed,
            shape_profile=shape_profile,
            distance=observer_distance,
            source_position=source_position,
            observer_heading_deg=observer_heading_deg,
        )

        audio["trajectory"] = {
            "peak_altitude": round(peak_altitude, 1),
            "estimated_range": round(final_range, 1),
            "flight_time": round(flight_time, 2),
            "point_count": len(trajectory),
        }
        return audio
    except Exception as e:
        logger.error(f"Error in launch audio params: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/launch/experience")
async def launch_experience(req: LaunchExperienceRequest):
    try:
        trajectory = aero_sim.calculate_trajectory(req.velocity, req.launch_angle, req.rotation_speed)

        peak_altitude = max((p["altitude"] for p in trajectory), default=0)
        final_range = trajectory[-1]["x"] if trajectory else 0
        flight_time = trajectory[-1]["time"] if trajectory else 0

        aero_result = shape_aero_sim.simulate_shape(
            req.velocity, req.shape_profile, 0.0, req.rotation_speed
        )
        ac_result = acoustics_sim.simulate(req.velocity, req.rotation_speed, req.observer_distance)

        obs_heading = getattr(req, "observer_heading_deg", 0.0) or 0.0
        source_position = (req.observer_distance * math.cos(math.radians(-obs_heading)),
                           req.observer_distance * math.sin(math.radians(-obs_heading)),
                           peak_altitude * 0.3 + 1.5)
        audio = _build_launch_audio(
            velocity=req.velocity,
            rotation_speed=req.rotation_speed,
            shape_profile=req.shape_profile,
            distance=req.observer_distance,
            source_position=source_position,
            observer_heading_deg=obs_heading,
        )

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
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# NEW v2 APIs (modular architecture)
# ============================================================

# ------------------------------
# v2 Shape Comparison
# ------------------------------

@app.get("/api/v2/shapes/profiles")
async def v2_get_shape_profiles():
    """v2 API: 获取形状配置与数据质量（使用 ShapeComparator 模块）"""
    try:
        return shape_comparator.get_shape_profiles()
    except Exception as e:
        logger.error(f"[v2] Error in get_shape_profiles: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v2/shapes/compare")
async def v2_compare_shapes(
    velocity: float = Query(..., gt=0),
    shapes: str = Query("conical,spherical,blunt,ogival"),
    angle_of_attack: float = Query(0.0),
    rotation_speed: float = Query(0.0),
    include_ranking: bool = Query(True),
):
    """v2 API: 多形状气动对比（使用 ShapeComparator 模块，含自动排序）"""
    try:
        shape_list = [s.strip() for s in shapes.split(",") if s.strip()]
        result = shape_comparator.compare(
            velocity=velocity,
            shapes=shape_list,
            angle_of_attack=angle_of_attack,
            rotation_speed=rotation_speed,
            include_data_quality=True,
        )
        return result.to_dict()
    except Exception as e:
        logger.error(f"[v2] Error in shape comparison: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v2/shapes/quality/{shape_name}")
async def v2_get_shape_quality(shape_name: str):
    """v2 API: 获取单个形状的数据质量评估"""
    try:
        return shape_comparator.get_shape_data_quality(shape_name)
    except Exception as e:
        logger.error(f"[v2] Error in shape quality: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------
# v2 Cross-Era Comparison
# ------------------------------

@app.get("/api/v2/era/models")
async def v2_get_era_models():
    """v2 API: 获取可用现代口哨型号列表"""
    try:
        return era_comparator.list_available_models()
    except Exception as e:
        logger.error(f"[v2] Error in era models: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v2/era/compare")
async def v2_compare_eras(
    velocity: float = Query(..., gt=0),
    rotation_speed: float = Query(100.0),
    distance: float = Query(1.0),
    modern_model: str = Query("fox40_classic"),
    modern_whistle_length: float = Query(None),
    modern_whistle_diameter: float = Query(None),
    mingdi_shape: str = Query("conical"),
):
    """v2 API: 跨时代声学对比（使用 EraComparator 模块）"""
    try:
        result = era_comparator.compare(
            velocity=velocity,
            rotation_speed=rotation_speed,
            distance=distance,
            modern_model=modern_model,
            modern_whistle_length=modern_whistle_length,
            modern_whistle_diameter=modern_whistle_diameter,
            mingdi_shape=mingdi_shape,
        )
        return result.to_dict()
    except Exception as e:
        logger.error(f"[v2] Error in era comparison: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------
# v2 Field Superposition
# ------------------------------

@app.get("/api/v2/field/patterns")
async def v2_get_field_patterns():
    """v2 API: 获取可用齐射阵型列表"""
    try:
        return {
            "patterns": field_superposer.get_available_patterns(),
            "backend_info": field_superposer.get_backend_info(),
        }
    except Exception as e:
        logger.error(f"[v2] Error in field patterns: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v2/field/superpose")
async def v2_superpose_field(req: VolleySimulationRequest):
    """v2 API: 声场叠加仿真（使用 FieldSuperposer 模块）"""
    try:
        backend = getattr(req, "backend", "numpy") or "numpy"
        superposer = FieldSuperposer(backend=backend)

        new_arrows = []
        for a in req.arrows:
            pos = list(a.position) if a.position else [0, 0]
            if len(pos) < 2:
                pos = pos + [0] * (2 - len(pos))
            x, y = float(pos[0]), float(pos[1])
            z = 1.6
            if len(pos) >= 3:
                z = float(pos[2])
            aid = a.arrow_id if hasattr(a, "arrow_id") else f"v-{id(a)}"
            try:
                id_int = int(str(aid).split("-")[-1]) if hasattr(a, "arrow_id") else len(new_arrows) + 1
            except Exception:
                id_int = len(new_arrows) + 1
            new_arrows.append(VolleyArrowConfig(
                id=id_int,
                x=x, y=y, z=z,
                velocity=a.velocity,
                rotation_speed=a.rotation_speed,
                shape_profile=getattr(a, "shape_profile", "conical") or "conical",
                spl_1m=a.sound_pressure_level,
                frequency=a.whistle_frequency,
            ))

        gs = int(req.grid_size)
        extent = float(req.grid_spacing) * float(gs)
        obs = list(req.observer_position) if req.observer_position else [0.0, 0.0, 1.5]
        while len(obs) < 3:
            obs.append(1.5 if len(obs) == 2 else 0.0)

        result = superposer.superpose(
            arrows=new_arrows,
            grid_size=gs,
            grid_extent=extent,
            observer_height=float(obs[2]),
            interference_threshold_db=3.0,
            listener_position=(float(obs[0]), float(obs[1]), float(obs[2])),
            listener_heading_deg=0.0,
            duration_sec=2.5,
            binaural=True,
        )
        return result.to_dict()
    except Exception as e:
        logger.error(f"[v2] Error in field superposition: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v2/field/preset")
async def v2_field_preset(
    pattern: str = Query("line"),
    count: int = Query(5, ge=1, le=20),
    velocity: float = Query(65.0, gt=0),
    rotation_speed: float = Query(100.0),
    spacing: float = Query(5.0, gt=0),
    backend: str = Query("auto"),
):
    """v2 API: 预设阵型声场叠加（使用 FieldSuperposer 模块）"""
    try:
        superposer = FieldSuperposer(backend=backend)
        preset_arrows = superposer.create_preset_arrows(
            pattern=pattern,
            count=count,
            velocity=velocity,
            rotation_speed=rotation_speed,
            spacing=spacing,
        )

        result = superposer.superpose(
            arrows=preset_arrows,
            listener_position=(0, 0, 1.5),
        )
        result_dict = result.to_dict()
        result_dict["pattern"] = pattern
        return result_dict
    except Exception as e:
        logger.error(f"[v2] Error in field preset: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------
# v2 VR Whistling Arrow
# ------------------------------

@app.get("/api/v2/vr/shapes")
async def v2_get_vr_shapes():
    """v2 API: 获取虚拟发射可用形状与音色"""
    try:
        return {
            "shapes": vr_whistling_arrow.get_available_shapes(),
            "timbres": vr_whistling_arrow.get_shape_timbres(),
        }
    except Exception as e:
        logger.error(f"[v2] Error in vr shapes: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v2/vr/launch")
async def v2_vr_launch(
    velocity: float = Query(65.0, gt=0),
    launch_angle_deg: float = Query(25.0, ge=5, le=80),
    rotation_speed: float = Query(100.0),
    shape_profile: str = Query("conical"),
    observer_distance: float = Query(30.0),
    observer_heading_deg: float = Query(0.0),
    duration_sec: float = Query(2.5),
):
    """v2 API: 虚拟发射体验（使用 VRWhistlingArrow 模块，角度以度为单位）"""
    try:
        launch_angle_rad = math.radians(launch_angle_deg)
        result = vr_whistling_arrow.launch(
            velocity=velocity,
            launch_angle=launch_angle_rad,
            rotation_speed=rotation_speed,
            shape_profile=shape_profile,
            observer_distance=observer_distance,
            observer_heading_deg=observer_heading_deg,
            duration_sec=duration_sec,
        )
        return result.to_dict()
    except Exception as e:
        logger.error(f"[v2] Error in vr launch: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v2/vr/launch")
async def v2_vr_launch_post(req: LaunchExperienceRequest):
    """v2 API: 虚拟发射体验（POST 版本）"""
    try:
        result = vr_whistling_arrow.launch(
            velocity=req.velocity,
            launch_angle=req.launch_angle,
            rotation_speed=req.rotation_speed,
            shape_profile=req.shape_profile,
            observer_distance=req.observer_distance,
            observer_heading_deg=getattr(req, "observer_heading_deg", 0.0) or 0.0,
        )
        return result.to_dict()
    except Exception as e:
        logger.error(f"[v2] Error in vr launch post: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v2/vr/trajectory")
async def v2_vr_estimate_trajectory(
    velocity: float = Query(65.0, gt=0),
    launch_angle_deg: float = Query(25.0),
    rotation_speed: float = Query(0.0),
):
    """v2 API: 快速估算弹道参数"""
    try:
        launch_angle_rad = math.radians(launch_angle_deg)
        return vr_whistling_arrow.estimate_trajectory(
            velocity=velocity,
            launch_angle=launch_angle_rad,
            rotation_speed=rotation_speed,
        )
    except Exception as e:
        logger.error(f"[v2] Error in trajectory estimate: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------
# v2 CFD Worker (async)
# ------------------------------

@app.get("/api/v2/cfd/job-types")
async def v2_cfd_job_types():
    """v2 API: 获取可用 CFD 任务类型"""
    try:
        return {
            "job_types": CFDWorker.VALID_JOB_TYPES,
            "worker_stats": cfd_worker.get_stats(),
        }
    except Exception as e:
        logger.error(f"[v2] Error in cfd job types: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v2/cfd/submit")
async def v2_cfd_submit(
    job_type: str = Query(..., description="CFD任务类型"),
    velocity: float = Query(..., gt=0, description="来流速度 m/s"),
    length_scale: float = Query(None, description="特征长度 m"),
    turbulence_intensity: float = Query(0.05, description="湍流强度"),
    priority: int = Query(5, ge=1, le=10, description="优先级1-10"),
):
    """v2 API: 提交异步 CFD 计算任务（独立 Worker 进程执行）"""
    try:
        params = {
            "velocity": velocity,
            "turbulence_intensity": turbulence_intensity,
        }
        if length_scale:
            params["length_scale"] = length_scale

        job_id = cfd_worker.submit_job(
            job_type=job_type,
            params=params,
            priority=priority,
        )
        return {
            "job_id": job_id,
            "status": CFDJobStatus.QUEUED.value,
            "job_type": job_type,
            "params": params,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[v2] Error in cfd submit: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v2/cfd/job/{job_id}")
async def v2_cfd_get_job(job_id: str, wait: float = Query(0.0, ge=0, le=10)):
    """v2 API: 查询 CFD 任务状态与结果"""
    try:
        job = cfd_worker.get_job_result(job_id, timeout=wait)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        return job.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[v2] Error in cfd get job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v2/cfd/jobs")
async def v2_cfd_list_jobs(status: str = Query(None, description="按状态过滤")):
    """v2 API: 列出所有 CFD 任务"""
    try:
        status_filter = None
        if status:
            try:
                status_filter = CFDJobStatus(status.lower())
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
        jobs = cfd_worker.list_jobs(status_filter=status_filter)
        return {
            "count": len(jobs),
            "jobs": [j.to_dict() for j in jobs],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[v2] Error in cfd list jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/v2/cfd/job/{job_id}")
async def v2_cfd_cancel_job(job_id: str):
    """v2 API: 取消排队中的 CFD 任务"""
    try:
        success = cfd_worker.cancel_job(job_id)
        if not success:
            raise HTTPException(status_code=400, detail=f"Cannot cancel job {job_id} (not found or already running/completed)")
        return {"job_id": job_id, "cancelled": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[v2] Error in cfd cancel job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v2/cfd/stats")
async def v2_cfd_stats():
    """v2 API: 获取 CFD Worker 统计信息"""
    try:
        return cfd_worker.get_stats()
    except Exception as e:
        logger.error(f"[v2] Error in cfd stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))
