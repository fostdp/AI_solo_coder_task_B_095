import math
from typing import List, Dict, Tuple
from ..config import settings


class VolleySimulation:
    def __init__(self, rho: float = None, c0: float = None):
        self.rho = rho or settings.air_density
        self.c0 = c0 or settings.speed_of_sound

    def simulate_volley(
        self,
        arrows: List[dict],
        grid_size: int = 40,
        grid_spacing: float = 2.0,
        observer_position: Tuple[float, float] = (0, 50),
    ) -> dict:
        individual_fields = []
        individual_results = []
        total_power = 0.0
        frequencies = []

        for arrow in arrows:
            vel = arrow["velocity"]
            rot = arrow.get("rotation_speed", 100.0)
            freq = arrow.get("whistle_frequency", 1500.0)
            spl = arrow.get("sound_pressure_level", 85.0)
            pos = arrow.get("position", (0.0, 0.0))

            freqs = {
                "fundamental": freq,
                "2nd_harmonic": freq * 2,
                "3rd_harmonic": freq * 3,
            }
            frequencies.append(freqs)

            ref_p = 2e-5
            p_rms = ref_p * 10 ** (spl / 20)
            acoustic_power = 4 * math.pi * p_rms ** 2 / (self.rho * self.c0)
            total_power += acoustic_power

            field = []
            for i in range(grid_size):
                row = []
                for j in range(grid_size):
                    x = (j - grid_size / 2) * grid_spacing
                    y = (i - grid_size / 2) * grid_spacing
                    dist = math.sqrt((x - pos[0]) ** 2 + (y - pos[1]) ** 2)
                    if dist < 0.1:
                        dist = 0.1

                    angle = math.atan2(y - pos[1], x - pos[0])
                    directivity = 1.0 + 0.3 * math.cos(angle) + 0.1 * math.cos(2 * angle)

                    local_spl = spl - 20 * math.log10(dist) + 10 * math.log10(max(directivity, 0.01))
                    row.append(local_spl)
                field.append(row)

            individual_fields.append(field)
            individual_results.append({
                "arrow_id": arrow.get("arrow_id", "unknown"),
                "position": pos,
                "velocity": vel,
                "whistle_frequency": freq,
                "sound_pressure_level": spl,
            })

        superposed = self._superpose_fields(individual_fields)

        obs_spl_values = []
        for arrow in arrows:
            pos = arrow.get("position", (0.0, 0.0))
            spl = arrow.get("sound_pressure_level", 85.0)
            dist = math.sqrt(
                (observer_position[0] - pos[0]) ** 2
                + (observer_position[1] - pos[1]) ** 2
            )
            if dist < 0.1:
                dist = 0.1
            obs_spl_values.append(spl - 20 * math.log10(dist))

        observer_spl = self._spl_sum(obs_spl_values)

        total_spl_source = self._spl_sum([a.get("sound_pressure_level", 85.0) for a in arrows])

        peak_field = max(max(row) for row in superposed)
        min_field = min(min(row) for row in superposed)

        interference_zones = self._detect_interference(superposed, grid_spacing)

        return {
            "arrow_count": len(arrows),
            "grid_size": grid_size,
            "grid_spacing": grid_spacing,
            "observer_position": observer_position,
            "observer_spl": round(observer_spl, 1),
            "total_acoustic_power_w": round(total_power, 6),
            "peak_spl_in_field": round(peak_field, 1),
            "min_spl_in_field": round(min_field, 1),
            "frequencies": frequencies,
            "individual_results": individual_results,
            "field": superposed,
            "interference_zones": interference_zones,
            "enhancement_vs_single_db": round(observer_spl - max(obs_spl_values), 1) if obs_spl_values else 0,
        }

    def _superpose_fields(self, fields: List[List[List[float]]]) -> List[List[float]]:
        if not fields:
            return []
        h = len(fields[0])
        w = len(fields[0][0])

        pressure_squares = [[[0.0] * w for _ in range(h)] for _ in range(h)]

        ref_p = 2e-5
        result = []
        for i in range(h):
            row = []
            for j in range(w):
                p_sq_sum = 0.0
                for field in fields:
                    p = ref_p * 10 ** (field[i][j] / 20)
                    p_sq_sum += p ** 2
                p_total = math.sqrt(p_sq_sum)
                spl = 20 * math.log10(p_total / ref_p) if p_total > 0 else 0
                row.append(round(spl, 2))
            result.append(row)
        return result

    def _spl_sum(self, spl_values: List[float]) -> float:
        ref_p = 2e-5
        p_sq_sum = 0.0
        for spl in spl_values:
            p = ref_p * 10 ** (spl / 20)
            p_sq_sum += p ** 2
        p_total = math.sqrt(p_sq_sum)
        return 20 * math.log10(p_total / ref_p) if p_total > 0 else 0

    def _detect_interference(self, field: List[List[float]], spacing: float) -> List[dict]:
        zones = []
        h = len(field)
        w = len(field[0]) if h > 0 else 0
        for i in range(1, h - 1):
            for j in range(1, w - 1):
                val = field[i][j]
                neighbors = [field[i-1][j], field[i+1][j], field[i][j-1], field[i][j+1]]
                avg_neighbor = sum(neighbors) / len(neighbors)
                if val - avg_neighbor > 3.0:
                    zones.append({
                        "type": "constructive",
                        "grid_i": i,
                        "grid_j": j,
                        "position_x": (j - w / 2) * spacing,
                        "position_y": (i - h / 2) * spacing,
                        "spl": val,
                        "enhancement_db": round(val - avg_neighbor, 1),
                    })
                elif avg_neighbor - val > 3.0:
                    zones.append({
                        "type": "destructive",
                        "grid_i": i,
                        "grid_j": j,
                        "position_x": (j - w / 2) * spacing,
                        "position_y": (i - h / 2) * spacing,
                        "spl": val,
                        "suppression_db": round(avg_neighbor - val, 1),
                    })

        constructive = [z for z in zones if z["type"] == "constructive"]
        destructive = [z for z in zones if z["type"] == "destructive"]
        return {
            "constructive_count": len(constructive),
            "destructive_count": len(destructive),
            "peak_constructive": max((z["enhancement_db"] for z in constructive), default=0),
            "peak_destructive": max((z["suppression_db"] for z in destructive), default=0),
            "zones": zones[:20],
        }


class AudioSynthesisParams:
    def __init__(self, rho: float = None, c0: float = None):
        self.rho = rho or settings.air_density
        self.c0 = c0 or settings.speed_of_sound

    def calculate(
        self,
        velocity: float,
        rotation_speed: float = 100.0,
        whistle_diameter: float = None,
        whistle_length: float = None,
        shape_profile: str = "conical",
        distance: float = 10.0,
        duration_seconds: float = 3.0,
    ) -> dict:
        from .shape_acoustics import SHAPE_PROFILES
        from .aeroacoustics import AeroAcousticsSimulator

        w_d = whistle_diameter or settings.whistle_diameter
        w_l = whistle_length or settings.whistle_length

        acoustic_sim = AeroAcousticsSimulator()
        acoustic_result = acoustic_sim.simulate(velocity, rotation_speed, distance)

        sp = SHAPE_PROFILES.get(shape_profile, SHAPE_PROFILES["conical"])

        fundamental = acoustic_result["whistle_frequency"]
        harmonic_ratios = [1.0, 2.0, 3.0, 4.17, 5.03]
        harmonic_amplitudes = [1.0, 0.45, 0.25, 0.12, 0.06]
        harmonic_amplitudes = [a * sp["whistle_efficiency"] for a in harmonic_amplitudes]

        harmonics = []
        for i, (ratio, amp) in enumerate(zip(harmonic_ratios, harmonic_amplitudes)):
            f = fundamental * ratio
            if f > 20000:
                break
            harmonics.append({
                "frequency": round(f, 1),
                "amplitude": round(amp, 4),
                "detune_cents": round((sp["whistle_cavity_coupling"] - 0.5) * 20 * (i + 1), 1),
            })

        spl = acoustic_result["sound_pressure_level"]
        perceived_loudness = 10 ** ((spl - 80) / 20) if spl > 0 else 0
        volume = min(1.0, max(0.0, perceived_loudness * 0.5))

        vibrato_rate = rotation_speed * 0.01 if rotation_speed > 0 else 3.0
        vibrato_depth = rotation_speed * 0.0005 if rotation_speed > 0 else 0.002

        attack_time = 0.05 + 0.02 * (1 - sp["whistle_efficiency"])
        decay_time = 0.3 + 0.1 * sp["surface_roughness"]
        sustain_level = 0.7 + 0.2 * sp["whistle_cavity_coupling"]
        release_time = 0.15

        return {
            "fundamental_frequency": round(fundamental, 1),
            "sample_rate": 44100,
            "duration_seconds": duration_seconds,
            "volume": round(volume, 3),
            "waveform_type": "composite_sawtooth_sine",
            "harmonics": harmonics,
            "adsr": {
                "attack": round(attack_time, 3),
                "decay": round(decay_time, 3),
                "sustain": round(sustain_level, 3),
                "release": round(release_time, 3),
            },
            "vibrato": {
                "rate_hz": round(vibrato_rate, 1),
                "depth_semitones": round(vibrato_depth * fundamental, 1),
            },
            "shape_profile": shape_profile,
            "perceived_pitch_hz": round(fundamental, 1),
            "timbre_descriptor": self._describe_timbre(sp, fundamental),
            "sound_pressure_level": round(spl, 1),
            "observer_distance": distance,
            "velocity": velocity,
            "rotation_speed": rotation_speed,
        }

    def _describe_timbre(self, sp: dict, freq: float) -> str:
        if sp["whistle_efficiency"] > 0.7 and freq > 1500:
            return "清亮尖锐"
        elif sp["whistle_efficiency"] > 0.7:
            return "通透明亮"
        elif sp["surface_roughness"] > 0.6:
            return "粗犷浑厚"
        elif freq > 2000:
            return "尖锐刺耳"
        elif freq > 1000:
            return "悠远苍凉"
        else:
            return "低沉悠长"
