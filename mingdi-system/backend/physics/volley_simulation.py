import math
import time
import logging
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    import cupy as _cp  # type: ignore

    _HAS_CUPY = True
except ImportError:
    _cp = None
    _HAS_CUPY = False


def _choose_backend(backend: str):
    backend = (backend or "auto").lower()
    if backend in ("cuda", "gpu", "cupy"):
        if _HAS_CUPY:
            return _cp, "cupy"
        raise RuntimeError("CuPy/CUDA 不可用，请安装 cupy-cuda11x 或改用 backend='numpy'")
    if backend == "numpy":
        return np, "numpy"
    if _HAS_CUPY:
        return _cp, "cupy"
    return np, "numpy"


_SHAPE_TIMBRE = {
    "conical": "sharp metallic",
    "spherical": "rich hollow",
    "blunt": "throaty gurgle",
    "ogival": "pure piercing",
}

_WAVETABLE_HARMONIC_RATIOS = [1.0, 2.0, 3.0, 4.17, 5.03]
_WAVETABLE_HARMONIC_GAINS = [1.0, 0.5, 0.28, 0.14, 0.07]


@dataclass
class VolleyArrowConfig:
    id: int
    x: float
    y: float
    z: float
    velocity: float
    rotation_speed: float = 80.0
    launch_angle: float = 0.0
    shape_profile: str = "conical"
    spl_1m: Optional[float] = None
    frequency: Optional[float] = None


@dataclass
class AudioSynthesisParams:
    waveform_type: str
    dominant_frequency: float
    harmonic_ratios: List[float]
    harmonic_gains: List[float]
    attack_sec: float
    decay_sec: float
    sustain_db: float
    release_sec: float
    vibrato_hz: float
    vibrato_depth_semitones: float
    total_duration_sec: float
    volume: float
    timbre_description: str
    spl_reference_db: float
    sample_rate_hz: int = 44100

    def calculate(self, binaural: bool = True, source_position=(10, 0, 0),
                  observer_heading_deg: float = 0.0, sample_rate_hz: int = 44100) -> dict:
        result = {
            "waveform_type": self.waveform_type,
            "dominant_frequency": round(self.dominant_frequency, 2),
            "harmonic_structure": [
                {"ratio": r, "gain": g, "frequency_hz": r * self.dominant_frequency}
                for r, g in zip(self.harmonic_ratios, self.harmonic_gains)
            ],
            "adsr_envelope": {
                "attack_sec": self.attack_sec,
                "decay_sec": self.decay_sec,
                "sustain_level_db": self.sustain_db,
                "release_sec": self.release_sec,
            },
            "vibrato": {
                "rate_hz": self.vibrato_hz,
                "depth_semitones": self.vibrato_depth_semitones,
            },
            "total_duration_sec": self.total_duration_sec,
            "output_volume": self.volume,
            "timbre": self.timbre_description,
            "spl_reference_db": self.spl_reference_db,
            "sample_rate_hz": sample_rate_hz,
        }
        if binaural:
            result["binaural"] = self._binaural_parameters(
                source_position, observer_heading_deg, sample_rate_hz
            )
        return result

    def _binaural_parameters(self, source_position, heading_deg: float,
                             sample_rate_hz: int) -> dict:
        from .shape_acoustics import BinauralSpatialAudio
        from ..config import settings
        b = BinauralSpatialAudio(c0=settings.speed_of_sound)
        stereo = b.stereo_gains(
            source_position=source_position,
            source_spl_db=self.spl_reference_db,
            observer_heading_deg=heading_deg,
        )
        sr = float(sample_rate_hz)
        bin_data = stereo["binaural"]
        left_delay_s = bin_data["itd_left_sec"]
        right_delay_s = bin_data["itd_right_sec"]
        return {
            "enabled": True,
            "hrir_coordinates": {
                "source_position_m": list(source_position),
                "observer_heading_deg": heading_deg,
                "azimuth_deg": bin_data["azimuth_deg"],
                "elevation_deg": bin_data["elevation_deg"],
                "distance_m": bin_data["distance_m"],
            },
            "itd_parameters": {
                "left_delay_sec": left_delay_s,
                "right_delay_sec": right_delay_s,
                "left_delay_samples": int(round(left_delay_s * sr)),
                "right_delay_samples": int(round(right_delay_s * sr)),
                "interaural_time_diff_us": bin_data["interaural_time_diff_us"],
            },
            "ild_parameters": {
                "left_channel_gain": stereo["left_channel_gain"],
                "right_channel_gain": stereo["right_channel_gain"],
                "left_channel_spl_db": stereo["left_channel_spl_db"],
                "right_channel_spl_db": stereo["right_channel_spl_db"],
                "interaural_level_diff_db": bin_data["interaural_level_diff_db"],
            },
            "hrtf_gains_db": {
                "left": bin_data["hrtf_gain_left_db"],
                "right": bin_data["hrtf_gain_right_db"],
                "elevation_correction_db": bin_data["elevation_gain_db"],
            },
            "recommended_rendering": {
                "use_stereo_panner": True,
                "apply_distance_attenuation_db": 20 * math.log10(max(bin_data["distance_m"], 0.01)),
                "apply_hrir_fir": True,
                "hrir_tap_count_earsim": 512,
            },
        }


class VolleySimulation:
    def __init__(self, rho: float = None, c0: float = None, mu: float = None,
                 backend: str = "auto"):
        from ..config import settings
        self.rho = rho or settings.air_density
        self.c0 = c0 or settings.speed_of_sound
        self.mu = mu or settings.air_viscosity
        self.settings = settings
        self._arrow_lib_fallback = None
        self.xp, self.backend_name = _choose_backend(backend)

    def _arrow_library(self):
        if self._arrow_lib_fallback is not None:
            return self._arrow_lib_fallback
        try:
            from .aeroacoustics import AeroAcousticsSimulator
            self._arrow_lib_fallback = AeroAcousticsSimulator(
                self.rho, self.c0, self.mu,
                AeroDynamicsSimulator_ctor=self._aero_ctor,
            )
        except Exception as e:
            logger.warning("[volley] AeroAcousticsSimulator 加载失败 %s", e)
            self._arrow_lib_fallback = None
        return self._arrow_lib_fallback

    def _aero_ctor(self):
        from .aerodynamics import AeroDynamicsSimulator
        return AeroDynamicsSimulator(self.rho, self.mu, self.c0)

    def _single_arrow_spl_freq(self, velocity: float, rotation_speed: float,
                               spl_1m_override: Optional[float],
                               freq_override: Optional[float],
                               distance: float = 1.0) -> Tuple[float, float]:
        if spl_1m_override is not None and freq_override is not None:
            spl_at_d = spl_1m_override - 20 * math.log10(max(distance, 0.01)) if distance > 0 else spl_1m_override
            return freq_override, spl_at_d
        lib = self._arrow_library()
        if lib is not None:
            r = lib.simulate(velocity, rotation_speed, distance)
            return r["whistle_frequency"], r["sound_pressure_level"]
        f = 800 + velocity * 12
        spl = 60 + 40 * math.log10(max(velocity, 1) / 50) if velocity > 0 else 20
        spl -= 20 * math.log10(max(distance, 0.01))
        return f, spl

    def simulate_volley(
        self,
        arrows: List[VolleyArrowConfig],
        grid_size: int = 40,
        grid_extent: float = 30.0,
        observer_height: float = 1.5,
        interference_threshold_db: float = 3.0,
    ) -> dict:
        t0 = time.perf_counter()
        xp = self.xp
        arrows = list(arrows) or []
        N_arrows = len(arrows)

        if N_arrows == 0:
            return {
                "arrow_count": 0,
                "grid_size": grid_size,
                "grid_extent_m": grid_extent,
                "acoustic_backend": self.backend_name,
                "computation_ms": round((time.perf_counter() - t0) * 1000, 1),
                "spl_grid": [[0.0] * grid_size for _ in range(grid_size)],
                "frequency_grid": [[0.0] * grid_size for _ in range(grid_size)],
                "interference_regions": [],
                "total_acoustic_power_w": 0.0,
                "arrow_sources": [],
                "centroid_db": 0.0,
            }

        if grid_size <= 1:
            grid_size = 2

        half = grid_extent / 2
        xs_np = np.linspace(-half, half, grid_size, dtype=np.float64)
        ys_np = np.linspace(-half, half, grid_size, dtype=np.float64)

        grid_shape = (grid_size, grid_size)
        spl_fields_linear = np.zeros((N_arrows, grid_size, grid_size), dtype=np.float64)
        freq_grid = np.zeros(grid_shape, dtype=np.float64)
        weight_sum = np.zeros(grid_shape, dtype=np.float64)

        ref_pa = 2e-5
        src_positions = []
        arrow_source_info = []
        total_power = 0.0
        centroid_x = 0.0
        centroid_y = 0.0
        center_weight = 0.0

        for i, a in enumerate(arrows):
            f_hz, spl_1m = self._single_arrow_spl_freq(a.velocity, a.rotation_speed, a.spl_1m, a.frequency, 1.0)
            p_ref_pa = ref_pa * 10 ** (spl_1m / 20)
            src_positions.append((float(a.x), float(a.y), float(a.z), p_ref_pa, f_hz))
            power = 4 * math.pi * (1.0 ** 2) * (p_ref_pa ** 2) / 415.0
            total_power += power
            arrow_source_info.append({
                "id": a.id,
                "position_m": [a.x, a.y, a.z],
                "frequency_hz": round(f_hz, 1),
                "spl_1m_db": round(spl_1m, 1),
                "shape_profile": a.shape_profile,
                "velocity_m_s": a.velocity,
                "power_w": round(power, 6),
            })
            centroid_x += spl_1m * a.x
            centroid_y += spl_1m * a.y
            center_weight += spl_1m

        if N_arrows >= 1:
            try:
                X_g, Y_g = np.meshgrid(xs_np, ys_np, indexing="xy")
                Z_plane = float(observer_height)
                all_dx = np.zeros((N_arrows, grid_size, grid_size), dtype=np.float64)
                all_dy = np.zeros_like(all_dx)
                all_dz = np.zeros_like(all_dx)
                all_pref = np.zeros((N_arrows, 1, 1), dtype=np.float64)
                all_freqs = np.zeros((N_arrows, 1, 1), dtype=np.float64)
                for i, (ax, ay, az, pref, f_hz) in enumerate(src_positions):
                    all_dx[i] = X_g - ax
                    all_dy[i] = Y_g - ay
                    all_dz[i] = Z_plane - az
                    all_pref[i, 0, 0] = pref
                    all_freqs[i, 0, 0] = f_hz

                dists = np.sqrt(all_dx ** 2 + all_dy ** 2 + all_dz ** 2)
                dists_safe = np.where(dists < 0.01, 0.01, dists)

                if self.backend_name == "cupy" and _HAS_CUPY:
                    d_gpu = xp.asarray(dists_safe)
                    pref_gpu = xp.asarray(all_pref)
                    p_field_gpu = pref_gpu / (4 * math.pi * xp.maximum(d_gpu, 0.01))
                    spl_fields_gpu = 20 * xp.log10(xp.maximum(p_field_gpu, 1e-18) / ref_pa)
                    spl_fields_linear = xp.asnumpy(spl_fields_gpu).astype(np.float64)
                    freq_grid_cpu = all_freqs[:, 0, 0, 0]
                    for i in range(N_arrows):
                        power_weight = np.maximum(10 ** (spl_fields_linear[i] / 20), 1e-12)
                        freq_grid += power_weight * freq_grid_cpu[i]
                        weight_sum += power_weight
                else:
                    p_field = all_pref / (4 * math.pi * dists_safe)
                    spl_fields_linear = 20 * np.log10(np.maximum(p_field, 1e-18) / ref_pa)
                    freq_grid_cpu = all_freqs[:, 0, 0, 0]
                    for i in range(N_arrows):
                        power_weight = np.maximum(10 ** (spl_fields_linear[i] / 20), 1e-12)
                        freq_grid += power_weight * freq_grid_cpu[i]
                        weight_sum += power_weight
            except Exception as e:
                logger.warning("[volley] 向量化路径失败 %s，回退标量循环", e)
                X_g, Y_g = np.meshgrid(xs_np, ys_np, indexing="xy")
                Z_plane = float(observer_height)
                for i, (ax, ay, az, pref, f_hz) in enumerate(src_positions):
                    dx = X_g - ax
                    dy = Y_g - ay
                    dz = Z_plane - az
                    d = np.sqrt(dx ** 2 + dy ** 2 + dz ** 2)
                    d_safe = np.where(d < 0.01, 0.01, d)
                    p = pref / (4 * math.pi * d_safe)
                    spl = 20 * np.log10(np.maximum(p, 1e-18) / ref_pa)
                    spl_fields_linear[i] = spl
                    pw = np.maximum(10 ** (spl / 20), 1e-12)
                    freq_grid += pw * f_hz
                    weight_sum += pw

        fields_linear = 10 ** (spl_fields_linear / 20)
        total_linear = np.sqrt(np.sum(fields_linear ** 2, axis=0))
        total_linear = np.where(total_linear < 1e-12, 1e-12, total_linear)
        total_spl = 20 * np.log10(total_linear)
        total_spl = np.where(np.isfinite(total_spl), total_spl, 0.0)

        interference_mask = np.zeros(grid_shape, dtype=bool)
        if N_arrows >= 2:
            incoherent_db = 10 * np.log10(N_arrows) + spl_fields_linear[0] * 0 + np.mean(spl_fields_linear, axis=0)
            diff = np.abs(total_spl - incoherent_db)
            interference_mask = diff > interference_threshold_db
        interference_regions = []
        if np.any(interference_mask):
            ys_idx, xs_idx = np.where(interference_mask)
            if len(ys_idx) > 0:
                interference_regions.append({
                    "type": "constructive_destructive_alternating",
                    "grid_points_affected": int(len(ys_idx)),
                    "grid_ratio": round(float(len(ys_idx)) / float(grid_size * grid_size), 3),
                    "threshold_db": interference_threshold_db,
                    "representative_points": [
                        {
                            "grid_x_idx": int(xs_idx[k]),
                            "grid_y_idx": int(ys_idx[k]),
                            "world_m": [float(xs_np[xs_idx[k]]), float(ys_np[ys_idx[k]]), float(observer_height)],
                            "local_spl_db": float(total_spl[ys_idx[k], xs_idx[k]]),
                        }
                        for k in range(min(5, len(ys_idx)))
                    ],
                })

        nonzero_mask = weight_sum > 1e-12
        freq_grid_out = np.where(nonzero_mask, freq_grid / np.where(nonzero_mask, weight_sum, 1), 0.0)

        center_i = grid_size // 2
        center_j = grid_size // 2
        centroid_db = float(total_spl[center_j, center_i]) if (grid_size > 0) else 0.0

        total_ms = round((time.perf_counter() - t0) * 1000, 2)
        perf_hint = None
        if N_arrows * grid_size * grid_size > 20000 and self.backend_name != "cupy":
            perf_hint = "建议启用CuDA: backend='cupy' (需安装 cupy-cuda11x)"

        return {
            "arrow_count": N_arrows,
            "grid_size": grid_size,
            "grid_extent_m": grid_extent,
            "acoustic_backend": self.backend_name,
            "computation_ms": total_ms,
            "performance_hint": perf_hint,
            "spl_grid": total_spl.tolist(),
            "frequency_grid": freq_grid_out.tolist(),
            "x_axis_m": xs_np.tolist(),
            "y_axis_m": ys_np.tolist(),
            "interference_regions": interference_regions,
            "total_acoustic_power_w": round(total_power, 6),
            "sound_centroid_m": [
                round(centroid_x / center_weight, 2) if center_weight > 0 else 0.0,
                round(centroid_y / center_weight, 2) if center_weight > 0 else 0.0,
            ],
            "arrow_sources": arrow_source_info,
            "centroid_db": round(centroid_db, 1),
        }

    def get_audio_synthesis_params(
        self,
        volley_result: dict,
        listener_position: Tuple[float, float, float] = (0, 0, 0),
        listener_heading_deg: float = 0.0,
        waveform_type: str = "sawtooth",
        duration_sec: float = 2.5,
    ) -> AudioSynthesisParams:
        arrows = volley_result.get("arrow_sources", [])
        if not arrows:
            return AudioSynthesisParams(
                waveform_type=waveform_type,
                dominant_frequency=800.0,
                harmonic_ratios=list(_WAVETABLE_HARMONIC_RATIOS),
                harmonic_gains=list(_WAVETABLE_HARMONIC_GAINS),
                attack_sec=0.005,
                decay_sec=0.2,
                sustain_db=-12,
                release_sec=0.35,
                vibrato_hz=6.0,
                vibrato_depth_semitones=0.25,
                total_duration_sec=duration_sec,
                volume=0.0,
                timbre_description="silence (no arrows)",
                spl_reference_db=0.0,
            )

        lx, ly, lz = listener_position
        closest = None
        min_dist = float("inf")
        total_spl_ref = 0.0
        total_freq = 0.0
        total_weight = 0.0
        total_rot = 0.0
        for a in arrows:
            ax, ay, az = a["position_m"]
            d = math.sqrt((ax - lx) ** 2 + (ay - ly) ** 2 + (az - lz) ** 2)
            f = float(a["frequency_hz"])
            spl1m = float(a["spl_1m_db"])
            spl_at_ear = spl1m - 20 * math.log10(max(d, 0.01))
            w = 10 ** (spl_at_ear / 20)
            total_freq += w * f
            total_spl_ref = max(total_spl_ref, spl_at_ear)
            total_weight += w
            v = float(a.get("velocity_m_s", 50))
            rot = max(20.0, min(300.0, 0.8 * v + 40))
            total_rot += w * rot
            if d < min_dist:
                min_dist = d
                closest = a

        avg_f = total_freq / total_weight if total_weight > 0 else 800.0
        avg_rot = total_rot / total_weight if total_weight > 0 else 80.0
        shape = closest.get("shape_profile", "conical") if closest else "conical"
        timbre = _SHAPE_TIMBRE.get(shape, "generic whistle")

        vib_hz = 5.0 + 0.02 * avg_rot
        vib_depth = 0.15 + 0.004 * avg_rot
        vib_depth = min(1.2, vib_depth)

        attack = 0.004 if len(arrows) >= 5 else 0.008
        decay = 0.18
        sustain = -14 + min(10, len(arrows))
        release = 0.30 + 0.01 * len(arrows)

        max_spl = 105.0
        vol_raw = 10 ** ((total_spl_ref - max_spl) / 20)
        vol = max(0.0, min(1.0, vol_raw * 1.5))

        return AudioSynthesisParams(
            waveform_type=waveform_type,
            dominant_frequency=float(avg_f),
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
            timbre_description=timbre,
            spl_reference_db=round(total_spl_ref, 1),
        )


def create_preset_volley(preset: str = "marching_10") -> List[VolleyArrowConfig]:
    if preset == "marching_10":
        arrows = []
        for i in range(10):
            x = -8 + (i % 5) * 3.5
            y = -6 + (i // 5) * 4
            z = 1.5
            arrows.append(VolleyArrowConfig(
                id=i + 1,
                x=round(x, 2), y=round(y, 2), z=z,
                velocity=60 + (i % 3) * 5,
                rotation_speed=70 + i * 4,
                launch_angle=0.087,
                shape_profile="conical" if i % 2 == 0 else "spherical",
            ))
        return arrows
    if preset == "ambush_20":
        arrows = []
        for i in range(20):
            r = 5 + (i % 4) * 2
            theta = (i / 20) * 2 * math.pi
            arrows.append(VolleyArrowConfig(
                id=i + 1,
                x=round(r * math.cos(theta), 2),
                y=round(r * math.sin(theta), 2),
                z=1.6,
                velocity=70,
                rotation_speed=90,
                launch_angle=0.105,
                shape_profile="blunt",
            ))
        return arrows
    if preset == "scouts_3":
        return [
            VolleyArrowConfig(id=1, x=-10, y=0, z=1.6, velocity=55, rotation_speed=80,
                              launch_angle=0.087, shape_profile="conical"),
            VolleyArrowConfig(id=2, x=0, y=-10, z=1.6, velocity=58, rotation_speed=75,
                              launch_angle=0.087, shape_profile="spherical"),
            VolleyArrowConfig(id=3, x=10, y=5, z=1.6, velocity=62, rotation_speed=85,
                              launch_angle=0.105, shape_profile="ogival"),
        ]
    if preset == "single":
        return [
            VolleyArrowConfig(id=1, x=5, y=0, z=1.6, velocity=70, rotation_speed=100,
                              launch_angle=0.087, shape_profile="conical"),
        ]
    raise ValueError(f"未知 preset: {preset}, 可选: marching_10, ambush_20, scouts_3, single")
