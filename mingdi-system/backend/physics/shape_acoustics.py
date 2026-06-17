import math
import logging
from typing import List, Dict, Optional, Tuple
from ..config import settings
from ..config_loader import extract_mingdi_shape_profile, get_modern_whistle_defaults

logger = logging.getLogger(__name__)

_PROVENANCE_RANK = {"windtunnel": 0, "archaeology": 1, "literature": 2, "fallback": 3, "unknown": 99}

_FALLBACK_SHAPE_PROFILES = {
    "conical": {
        "cd_base": 0.80, "cd_aoa_coeff": 3.5, "cl_alpha": 2.0, "stall_angle": 0.35,
        "pressure_peak": 1.2, "pressure_gradient": 0.85, "whistle_strouhal": 0.18,
        "whistle_cavity_coupling": 0.6, "whistle_efficiency": 0.8, "surface_roughness": 0.3,
    },
    "spherical": {
        "cd_base": 1.20, "cd_aoa_coeff": 5.0, "cl_alpha": 0.8, "stall_angle": 0.15,
        "pressure_peak": 1.8, "pressure_gradient": 0.5, "whistle_strouhal": 0.21,
        "whistle_cavity_coupling": 0.3, "whistle_efficiency": 0.5, "surface_roughness": 0.7,
    },
    "blunt": {
        "cd_base": 1.50, "cd_aoa_coeff": 4.5, "cl_alpha": 1.0, "stall_angle": 0.20,
        "pressure_peak": 2.0, "pressure_gradient": 0.4, "whistle_strouhal": 0.22,
        "whistle_cavity_coupling": 0.4, "whistle_efficiency": 0.6, "surface_roughness": 0.8,
    },
    "ogival": {
        "cd_base": 0.60, "cd_aoa_coeff": 3.0, "cl_alpha": 2.2, "stall_angle": 0.40,
        "pressure_peak": 1.0, "pressure_gradient": 0.95, "whistle_strouhal": 0.16,
        "whistle_cavity_coupling": 0.7, "whistle_efficiency": 0.9, "surface_roughness": 0.2,
    },
}

SHAPE_PROFILES = {k: dict(v) for k, v in _FALLBACK_SHAPE_PROFILES.items()}

try:
    for sname in list(_FALLBACK_SHAPE_PROFILES.keys()):
        numeric, _prov, _warn = extract_mingdi_shape_profile(sname)
        missing = [k for k in _FALLBACK_SHAPE_PROFILES[sname] if k not in numeric]
        if missing and sname in ("conical", "spherical"):
            logger.warning(
                "[mingdi-profiles] %s: 以下参数未在 config/mingdi_profiles.json 中实验测定，使用理论推断值: %s",
                sname, missing,
            )
        for k, v in numeric.items():
            SHAPE_PROFILES[sname][k] = v
except Exception as e:
    logger.warning("[mingdi-profiles] 加载实验测定参数失败，回退理论默认值: %s", e)


def get_shape_data_quality(shape_name: str) -> Dict:
    try:
        _, prov, warnings = extract_mingdi_shape_profile(shape_name)
    except Exception:
        prov = {}
        warnings = []
    worst_rank = -1
    for _, p in prov.items():
        rank = _PROVENANCE_RANK.get(p.get("provenance", "unknown"), 99)
        worst_rank = max(worst_rank, rank)
    rank_map = {v: k for k, v in _PROVENANCE_RANK.items()}
    worst_label = rank_map.get(worst_rank, "unknown")
    fallback_params = [k for k, v in prov.items() if v.get("provenance") == "fallback"]
    return {
        "shape": shape_name,
        "worst_provenance": worst_label,
        "total_params_measured": len(prov) - len(fallback_params),
        "total_params_expected": 10,
        "fallback_params": fallback_params,
        "warnings": warnings,
        "is_experimentally_validated": worst_rank <= 1,
    }


class ShapeAwareAeroSimulator:
    def __init__(self, rho: float = None, mu: float = None, c0: float = None):
        self.rho = rho or settings.air_density
        self.mu = mu or settings.air_viscosity
        self.c0 = c0 or settings.speed_of_sound

    def simulate_shape(
        self,
        velocity: float,
        shape_profile: str = "conical",
        angle_of_attack: float = 0.0,
        rotation_speed: float = 0.0,
        arrow_diameter: float = None,
        arrow_length: float = None,
        arrow_mass: float = None,
    ) -> dict:
        D = arrow_diameter or settings.arrow_diameter
        L = arrow_length or settings.arrow_length
        mass = arrow_mass or settings.arrow_mass
        frontal_area = math.pi * (D / 2) ** 2

        sp = SHAPE_PROFILES.get(shape_profile, SHAPE_PROFILES["conical"])
        re = self.rho * velocity * D / self.mu
        mach = velocity / self.c0

        cd_base = sp["cd_base"]
        cd_re_peak = 0.3 * math.exp(-((re - 3e3) / 8e3) ** 2)
        cd_aoa = sp["cd_aoa_coeff"] * math.sin(angle_of_attack) ** 2

        cd_compressibility = 0.0
        if mach > 0.3:
            cd_compressibility = 0.4 * (mach - 0.3) ** 2
        if mach > 0.8:
            beta_pg = math.sqrt(abs(1 - mach ** 2))
            cd_wave = 0.8 / max(beta_pg, 0.05) - 0.8
            cd_wave = min(cd_wave, 2.5)
            cd_compressibility += cd_wave * math.exp(-3 * (mach - 1.0) ** 2)
        if mach > 1.0:
            cd_supersonic = sp["cd_base"] * 1.3 * (1 - 0.3 * math.exp(-0.5 * (mach - 1.0)))
            cd_compressibility = max(cd_compressibility, cd_supersonic - cd_base)

        roughness_correction = sp["surface_roughness"] * 0.05 * math.log10(max(re, 100) / 1e4)
        cd = cd_base + cd_re_peak + cd_aoa + cd_compressibility + roughness_correction

        cl_alpha = sp["cl_alpha"]
        stall_angle = sp["stall_angle"]
        if abs(angle_of_attack) < stall_angle:
            cl = cl_alpha * angle_of_attack * (1 - 0.3 * abs(angle_of_attack))
        else:
            sign = 1 if angle_of_attack > 0 else -1
            cl = sign * cl_alpha * stall_angle * math.exp(-(abs(angle_of_attack) - stall_angle) / 0.2)

        if 0 < mach < 1.0:
            cl /= math.sqrt(max(1 - mach ** 2, 0.01))
        elif mach >= 1.0:
            cl /= math.sqrt(mach ** 2 - 1 + 0.01)
        cl = max(min(cl, 3.0), -3.0)

        q = 0.5 * self.rho * velocity ** 2
        drag = cd * q * frontal_area
        lift = cl * q * frontal_area
        magnus = 0.001 * self.rho * velocity * rotation_speed * D * L * abs(math.sin(angle_of_attack))
        lift += magnus
        moment = lift * L * 0.15 - drag * D * 0.3

        num_pts = 20
        pressure_dist = []
        for i in range(num_pts):
            x = i / (num_pts - 1)
            cp = sp["pressure_peak"] * (1 - sp["pressure_gradient"] * x) - 0.1 * math.sin(math.pi * x) * math.exp(-x * 2)
            pressure_dist.append(q * cp)

        quality = get_shape_data_quality(shape_profile)

        return {
            "shape_profile": shape_profile,
            "velocity": velocity,
            "angle_of_attack": angle_of_attack,
            "rotation_speed": rotation_speed,
            "reynolds_number": re,
            "mach_number": mach,
            "drag_coefficient": cd,
            "lift_coefficient": cl,
            "drag_force": drag,
            "lift_force": lift,
            "moment": moment,
            "pressure_distribution": pressure_dist,
            "shape_parameters": {
                "cd_base": sp["cd_base"],
                "cl_alpha": sp["cl_alpha"],
                "stall_angle": sp["stall_angle"],
                "surface_roughness": sp["surface_roughness"],
            },
            "data_quality": {
                "worst_provenance": quality["worst_provenance"],
                "experimentally_measured_params": quality["total_params_measured"],
                "fallback_params": quality["fallback_params"],
                "warnings": quality["warnings"],
                "is_experimentally_validated": quality["is_experimentally_validated"],
            },
        }

    def compare_shapes(
        self,
        velocity: float,
        shapes: List[str] = None,
        angle_of_attack: float = 0.0,
        rotation_speed: float = 0.0,
    ) -> Dict[str, dict]:
        if shapes is None:
            shapes = list(SHAPE_PROFILES.keys())
        results = {}
        for shape in shapes:
            results[shape] = self.simulate_shape(velocity, shape, angle_of_attack, rotation_speed)
        return results


class ModernWhistleAcousticSimulator:
    def __init__(self, rho: float = None, c0: float = None):
        self.rho = rho or settings.air_density
        self.c0 = c0 or settings.speed_of_sound

    def simulate_modern_whistle(
        self,
        velocity: float,
        whistle_length: float = None,
        whistle_diameter: float = None,
        mouth_width: float = None,
        model_name: str = None,
    ) -> dict:
        meta = get_modern_whistle_defaults(model_name)
        L_w = whistle_length if whistle_length is not None else meta["whistle_length"]
        D_w = whistle_diameter if whistle_diameter is not None else meta["whistle_diameter"]
        m_w = mouth_width if mouth_width is not None else meta["mouth_width"]
        st_jet = meta.get("strouhal_jet", 0.50)

        re = self.rho * velocity * D_w / settings.air_viscosity

        f_jet = st_jet * velocity / max(m_w, 1e-6)

        f_cavity = self.c0 / (2 * L_w) * (1 + 0.6 * D_w / L_w)

        dom_mult = meta.get("dominant_frequency_multiplier", 0.75)
        harmonic_mult_list = meta.get("harmonic_multipliers", [1.0, 2.0, 3.0, 4.0])

        f_dominant = dom_mult * f_cavity
        f_harmonics = [f_dominant * n for n in harmonic_mult_list]

        if re < 1000:
            eff = 5e-6 * re
        elif re < 10000:
            eff = 5e-3 * (re / 1000) ** 0.3
        else:
            eff = 0.02 * (1.0 - math.exp(-(re - 10000) / 50000))
            eff = 0.002 + 0.023 * (1.0 - math.exp(-re / 60000))

        ref_area = math.pi * (D_w / 2) ** 2
        acoustic_power = eff * 0.5 * self.rho * velocity ** 3 * ref_area

        ref_intensity = 1e-12
        spl_1m = 10 * math.log10(acoustic_power / (4 * math.pi * ref_intensity))

        if meta.get("measured_spl_1m_db"):
            m_spl = meta["measured_spl_1m_db"]
            v_ref = 65.0
            v_correction = 30 * math.log10(max(velocity, 1) / v_ref) if velocity > 0 else -40
            spl_1m = 0.6 * spl_1m + 0.4 * (m_spl + v_correction)

        directivity = []
        for i in range(36):
            theta = 2 * math.pi * i / 36
            d = 0.8 + 0.4 * math.cos(theta) + 0.1 * math.cos(3 * theta)
            directivity.append(d)

        return {
            "type": "modern_sports_whistle",
            "mechanism": "jet_edge_tone_cavity",
            "model_id": meta["model_name"],
            "display_name": meta["display_name"],
            "certifications": meta["certifications"],
            "mouthpiece_type": meta["mouthpiece_type"],
            "chamber_count": meta["chamber_count"],
            "standard_reference": "FOX 40 Classic (FIFA/FIBA/FINA 认证)" if meta["model_name"] == "fox40_classic" else None,
            "dominant_frequency": round(f_dominant, 1),
            "harmonic_frequencies": [round(f, 1) for f in f_harmonics],
            "cavity_resonance_freq": round(f_cavity, 1),
            "jet_edge_freq": round(f_jet, 1),
            "measured_dominant_frequency_hz": meta.get("measured_dominant_frequency_hz"),
            "measured_spl_1m_db": meta.get("measured_spl_1m_db"),
            "frequency_deviation_from_measured_pct": (
                round(100 * abs(f_dominant - meta["measured_dominant_frequency_hz"]) / meta["measured_dominant_frequency_hz"], 1)
                if meta.get("measured_dominant_frequency_hz") and meta["measured_dominant_frequency_hz"] > 0
                else None
            ),
            "sound_pressure_level_1m": round(spl_1m, 1),
            "acoustic_power_w": round(acoustic_power, 6),
            "efficiency": round(eff, 6),
            "reynolds_number": round(re, 0),
            "directivity_pattern": [round(d, 3) for d in directivity],
            "whistle_length_m": L_w,
            "whistle_diameter_m": D_w,
            "mouth_width_m": m_w,
        }


class CrossEraAcousticComparator:
    def __init__(self):
        from .aerodynamics import AeroDynamicsSimulator
        from .aeroacoustics import AeroAcousticsSimulator
        self.mingdi_aero = AeroDynamicsSimulator()
        self.mingdi_acoustic = AeroAcousticsSimulator()
        self.modern_whistle = ModernWhistleAcousticSimulator()

    def compare(
        self,
        velocity: float,
        rotation_speed: float = 100.0,
        distance: float = 1.0,
        modern_model: str = None,
        modern_whistle_length: float = None,
        modern_whistle_diameter: float = None,
    ) -> dict:
        mingdi_result = self.mingdi_acoustic.simulate(velocity, rotation_speed, distance)

        modern_result = self.modern_whistle.simulate_modern_whistle(
            velocity, modern_whistle_length, modern_whistle_diameter, model_name=modern_model
        )

        m_freq = mingdi_result["whistle_frequency"]
        w_freq = modern_result["dominant_frequency"]
        m_spl = mingdi_result["sound_pressure_level"]
        w_spl = modern_result["sound_pressure_level_1m"]

        freq_ratio = m_freq / w_freq if w_freq > 0 else 0
        spl_diff = m_spl - w_spl

        m_range = mingdi_result["propagation_distance"]
        w_range = 10 ** ((w_spl - 20) / 20) if w_spl > 20 else 0

        m_harmonics = [m_freq * n for n in range(1, 6)]
        w_harmonics = modern_result["harmonic_frequencies"]

        mingdi_quality = get_shape_data_quality("conical")

        return {
            "velocity": velocity,
            "rotation_speed": rotation_speed,
            "observer_distance": distance,
            "standardization_note": (
                "现代口哨参数基于FOX 40 Classic（FIFA/FIBA认证裁判哨）实物测量。"
                "鸣镝锥形参数基于满城汉墓出土实物+风洞实验校准。"
                + (f" 注意: {'; '.join(mingdi_quality['warnings'])}" if mingdi_quality["warnings"] else "")
            ),
            "mingdi": {
                "type": "ancient_mingdi",
                "mechanism": "cavity_resonance_vortex_shedding",
                "reference_artifact": "满城汉墓M2:4192 锥形铁首鸣镝",
                "whistle_frequency": round(m_freq, 1),
                "sound_pressure_level": round(m_spl, 1),
                "propagation_distance": round(m_range, 1),
                "strouhal_number": mingdi_result["strouhal_number"],
                "harmonic_frequencies": [round(f, 1) for f in m_harmonics],
                "source_breakdown": mingdi_result.get("source_breakdown", {}),
                "data_quality": {
                    "worst_provenance": mingdi_quality["worst_provenance"],
                    "experimentally_measured_count": mingdi_quality["total_params_measured"],
                    "fallback_params": mingdi_quality["fallback_params"],
                },
            },
            "modern_whistle": {
                "type": modern_result["type"],
                "mechanism": modern_result["mechanism"],
                "model_id": modern_result["model_id"],
                "display_name": modern_result["display_name"],
                "certifications": modern_result["certifications"],
                "whistle_frequency": round(w_freq, 1),
                "sound_pressure_level": round(w_spl, 1),
                "propagation_distance": round(w_range, 1),
                "harmonic_frequencies": w_harmonics,
                "cavity_resonance_freq": modern_result["cavity_resonance_freq"],
                "measured_dominant_frequency_hz": modern_result.get("measured_dominant_frequency_hz"),
                "measured_spl_1m_db": modern_result.get("measured_spl_1m_db"),
                "frequency_deviation_pct": modern_result.get("frequency_deviation_from_measured_pct"),
            },
            "comparison": {
                "frequency_ratio_mingdi_to_modern": round(freq_ratio, 3),
                "spl_difference_db": round(spl_diff, 1),
                "propagation_distance_ratio": round(m_range / w_range, 2) if w_range > 0 else 0,
                "dominant_harmonic_count_mingdi": len(m_harmonics),
                "dominant_harmonic_count_modern": len(w_harmonics),
                "era_gap_years": 2200,
                "key_insight": self._generate_insight(freq_ratio, spl_diff, m_freq, w_freq),
            },
        }

    def _generate_insight(self, freq_ratio: float, spl_diff: float, m_freq: float, w_freq: float) -> str:
        if freq_ratio < 0.5:
            return f"鸣镝频率({m_freq:.0f}Hz)远低于现代口哨({w_freq:.0f}Hz)，古代哨音偏深沉"
        elif freq_ratio < 1.0:
            return f"鸣镝频率({m_freq:.0f}Hz)低于现代口哨({w_freq:.0f}Hz)，但音色更具战争威慑感"
        elif freq_ratio < 1.5:
            return f"鸣镝与现代口哨频率接近({m_freq:.0f}Hz vs {w_freq:.0f}Hz)，但发声机制截然不同"
        else:
            return f"鸣镝频率({m_freq:.0f}Hz)高于现代口哨({w_freq:.0f}Hz)，哨音尖锐刺耳"


class BinauralSpatialAudio:
    EAR_SEPARATION_M = 0.165
    EAR_TO_CENTER_M = 0.0825

    def __init__(self, c0: float = None):
        self.c0 = c0 or settings.speed_of_sound

    def itd_ild(
        self,
        source_position: Tuple[float, float, float],
        observer_heading_deg: float = 0.0,
        observer_elevation_deg: float = 0.0,
    ) -> Dict[str, float]:
        sx, sy, sz = source_position
        h = math.radians(observer_heading_deg)
        ch, sh = math.cos(h), math.sin(h)
        dx = sx * ch + sy * sh
        dy = -sx * sh + sy * ch
        dz = sz

        dist = math.sqrt(dx ** 2 + dy ** 2 + dz ** 2) or 1e-6
        azimuth = math.atan2(dy, dx)

        itd_left = self.ear_time(azimuth, "left", dist)
        itd_right = self.ear_time(azimuth, "right", dist)

        ild_db = self._simplified_ild(azimuth, dist)

        hrtf_gain_left_db = self._simplified_hrtf(azimuth, "left")
        hrtf_gain_right_db = self._simplified_hrtf(azimuth, "right")

        elevation = math.atan2(dz, math.sqrt(dx ** 2 + dy ** 2))
        elev_filter_gain_db = -2 * abs(math.degrees(elevation)) / 90

        return {
            "itd_left_sec": round(itd_left, 8),
            "itd_right_sec": round(itd_right, 8),
            "interaural_time_diff_us": round((itd_right - itd_left) * 1e6, 2),
            "interaural_level_diff_db": round(ild_db, 2),
            "hrtf_gain_left_db": round(hrtf_gain_left_db, 2),
            "hrtf_gain_right_db": round(hrtf_gain_right_db, 2),
            "elevation_gain_db": round(elev_filter_gain_db, 2),
            "azimuth_deg": round(math.degrees(azimuth), 1),
            "elevation_deg": round(math.degrees(elevation), 1),
            "distance_m": round(dist, 3),
        }

    def ear_time(self, azimuth: float, side: str, source_distance: float) -> float:
        ear_y = self.EAR_TO_CENTER_M if side == "right" else -self.EAR_TO_CENTER_M
        src_x = source_distance * math.cos(azimuth)
        src_y = source_distance * math.sin(azimuth)
        d = math.sqrt(src_x ** 2 + (src_y - ear_y) ** 2)
        return d / self.c0

    def _simplified_ild(self, azimuth: float, distance: float) -> float:
        shadow_factor = 1.0 - math.exp(-distance / 0.5)
        return 15.0 * abs(math.sin(azimuth)) * shadow_factor

    def _simplified_hrtf(self, azimuth: float, side: str) -> float:
        sign = -1 if side == "left" else 1
        ipsilateral = sign * math.sin(azimuth) >= 0
        if ipsilateral:
            return 3.0 + 2.0 * abs(math.sin(azimuth))
        else:
            return -8.0 * abs(math.sin(azimuth))

    def stereo_gains(
        self,
        source_position: Tuple[float, float, float],
        source_spl_db: float,
        observer_heading_deg: float = 0.0,
        distance_attenuation_ref_m: float = 1.0,
    ) -> Dict[str, float]:
        binaural = self.itd_ild(source_position, observer_heading_deg)
        d = max(binaural["distance_m"], 0.01)
        dist_att_db = 20 * math.log10(d / distance_attenuation_ref_m)

        left_db = source_spl_db - dist_att_db + binaural["hrtf_gain_left_db"] + binaural["elevation_gain_db"]
        right_db = source_spl_db - dist_att_db + binaural["hrtf_gain_right_db"] + binaural["elevation_gain_db"]

        ref_p = 2e-5
        left_gain = 10 ** (left_db / 20) / (10 ** (source_spl_db / 20)) if source_spl_db > -999 else 0
        right_gain = 10 ** (right_db / 20) / (10 ** (source_spl_db / 20)) if source_spl_db > -999 else 0

        return {
            "left_channel_gain": round(max(0.0, min(left_gain, 10.0)), 6),
            "right_channel_gain": round(max(0.0, min(right_gain, 10.0)), 6),
            "left_channel_spl_db": round(left_db, 2),
            "right_channel_spl_db": round(right_db, 2),
            "binaural": binaural,
        }
