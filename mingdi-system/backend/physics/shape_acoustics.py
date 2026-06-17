import math
from typing import List, Dict
from ..config import settings


SHAPE_PROFILES = {
    "conical": {
        "cd_base": 0.80,
        "cd_aoa_coeff": 3.5,
        "cl_alpha": 2.0,
        "stall_angle": 0.35,
        "pressure_peak": 1.2,
        "pressure_gradient": 0.85,
        "whistle_strouhal": 0.18,
        "whistle_cavity_coupling": 0.6,
        "whistle_efficiency": 0.8,
        "surface_roughness": 0.3,
    },
    "spherical": {
        "cd_base": 1.20,
        "cd_aoa_coeff": 5.0,
        "cl_alpha": 0.8,
        "stall_angle": 0.15,
        "pressure_peak": 1.8,
        "pressure_gradient": 0.5,
        "whistle_strouhal": 0.21,
        "whistle_cavity_coupling": 0.3,
        "whistle_efficiency": 0.5,
        "surface_roughness": 0.7,
    },
    "blunt": {
        "cd_base": 1.50,
        "cd_aoa_coeff": 4.5,
        "cl_alpha": 1.0,
        "stall_angle": 0.20,
        "pressure_peak": 2.0,
        "pressure_gradient": 0.4,
        "whistle_strouhal": 0.22,
        "whistle_cavity_coupling": 0.4,
        "whistle_efficiency": 0.6,
        "surface_roughness": 0.8,
    },
    "ogival": {
        "cd_base": 0.60,
        "cd_aoa_coeff": 3.0,
        "cl_alpha": 2.2,
        "stall_angle": 0.40,
        "pressure_peak": 1.0,
        "pressure_gradient": 0.95,
        "whistle_strouhal": 0.16,
        "whistle_cavity_coupling": 0.7,
        "whistle_efficiency": 0.9,
        "surface_roughness": 0.2,
    },
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
        whistle_length: float = 0.025,
        whistle_diameter: float = 0.012,
        mouth_width: float = 0.004,
    ) -> dict:
        re = self.rho * velocity * whistle_diameter / settings.air_viscosity

        st_jet = 0.5
        f_jet = st_jet * velocity / mouth_width

        f_cavity = self.c0 / (2 * whistle_length) * (1 + 0.6 * whistle_diameter / whistle_length)

        f_dominant = 2.0 * f_cavity
        f_harmonics = [f_dominant * n for n in range(1, 5)]

        if re < 1000:
            eff = 5e-6 * re
        elif re < 10000:
            eff = 5e-3 * (re / 1000) ** 0.3
        else:
            eff = 0.02

        ref_area = math.pi * (whistle_diameter / 2) ** 2
        acoustic_power = eff * 0.5 * self.rho * velocity ** 3 * ref_area

        ref_intensity = 1e-12
        spl_1m = 10 * math.log10(acoustic_power / (4 * math.pi * ref_intensity))

        directivity = []
        for i in range(36):
            theta = 2 * math.pi * i / 36
            d = 0.8 + 0.4 * math.cos(theta) + 0.1 * math.cos(3 * theta)
            directivity.append(d)

        return {
            "type": "modern_sports_whistle",
            "mechanism": "jet_edge_tone_cavity",
            "dominant_frequency": round(f_dominant, 1),
            "harmonic_frequencies": [round(f, 1) for f in f_harmonics],
            "cavity_resonance_freq": round(f_cavity, 1),
            "jet_edge_freq": round(f_jet, 1),
            "sound_pressure_level_1m": round(spl_1m, 1),
            "acoustic_power_w": round(acoustic_power, 6),
            "efficiency": round(eff, 6),
            "reynolds_number": round(re, 0),
            "directivity_pattern": [round(d, 3) for d in directivity],
            "whistle_length_m": whistle_length,
            "whistle_diameter_m": whistle_diameter,
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
        modern_whistle_length: float = 0.025,
        modern_whistle_diameter: float = 0.012,
    ) -> dict:
        mingdi_result = self.mingdi_acoustic.simulate(velocity, rotation_speed, distance)

        modern_result = self.modern_whistle.simulate_modern_whistle(
            velocity, modern_whistle_length, modern_whistle_diameter
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

        return {
            "velocity": velocity,
            "rotation_speed": rotation_speed,
            "observer_distance": distance,
            "mingdi": {
                "type": "ancient_mingdi",
                "mechanism": "cavity_resonance_vortex_shedding",
                "whistle_frequency": round(m_freq, 1),
                "sound_pressure_level": round(m_spl, 1),
                "propagation_distance": round(m_range, 1),
                "strouhal_number": mingdi_result["strouhal_number"],
                "harmonic_frequencies": [round(f, 1) for f in m_harmonics],
                "source_breakdown": mingdi_result.get("source_breakdown", {}),
            },
            "modern_whistle": {
                "type": "modern_sports_whistle",
                "mechanism": modern_result["mechanism"],
                "whistle_frequency": round(w_freq, 1),
                "sound_pressure_level": round(w_spl, 1),
                "propagation_distance": round(w_range, 1),
                "harmonic_frequencies": w_harmonics,
                "cavity_resonance_freq": modern_result["cavity_resonance_freq"],
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
