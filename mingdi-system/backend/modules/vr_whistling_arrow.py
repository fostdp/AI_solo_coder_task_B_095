"""
虚拟发射体验模块 (vr_whistling_arrow)
独立封装公众虚拟发射响箭体验，用户可调节发射角度、速度、箭头形状，
聆听带有双耳空间音频的合成哨音。

职责：
- 弹道轨迹仿真
- 发射角度/速度/形状参数化调节
- Web Audio API 合成参数生成
- 双耳空间音频（ITD/ILD/HRTF）
- 音色随形状变化

依赖：
- physics.aerodynamics.AeroDynamicsSimulator
- physics.shape_acoustics.ShapeAwareAeroSimulator
- physics.aeroacoustics.AeroAcousticsSimulator
- physics.volley_simulation.AudioSynthesisParams
"""
import logging
import math
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

from ..physics import (
    AeroDynamicsSimulator,
    ShapeAwareAeroSimulator,
    AeroAcousticsSimulator,
    BinauralSpatialAudio,
)
from ..physics.volley_simulation import (
    AudioSynthesisParams,
    _SHAPE_TIMBRE,
    _WAVETABLE_HARMONIC_RATIOS,
    _WAVETABLE_HARMONIC_GAINS,
)

logger = logging.getLogger(__name__)


@dataclass
class LaunchExperienceRequest:
    velocity: float
    launch_angle: float
    rotation_speed: float = 100.0
    shape_profile: str = "conical"
    observer_distance: float = 30.0
    observer_heading_deg: float = 0.0
    duration_sec: float = 2.5


@dataclass
class LaunchExperienceResult:
    audio: Dict
    trajectory_summary: Dict
    aerodynamics: Optional[Dict]
    acoustics: Optional[Dict]

    def to_dict(self) -> dict:
        return {
            "audio": self.audio,
            "trajectory_summary": self.trajectory_summary,
            "aerodynamics": self.aerodynamics,
            "acoustics": self.acoustics,
        }


class VRWhistlingArrow:
    """
    虚拟发射响箭体验引擎，封装弹道仿真 + 双耳音频合成。

    Example:
        vr = VRWhistlingArrow()
        result = vr.launch(
            velocity=65.0,
            launch_angle=0.4,
            shape_profile="conical",
            observer_distance=30.0,
            observer_heading_deg=0.0,
        )
        # 返回音频合成参数，前端 Web Audio API 实时合成哨音
    """

    WAVEFORM_BY_SHAPE = {
        "conical": "sawtooth",
        "spherical": "square",
        "blunt": "triangle",
        "ogival": "sine",
    }

    def __init__(self):
        self.aero_sim = AeroDynamicsSimulator()
        self.shape_sim = ShapeAwareAeroSimulator()
        self.acoustics_sim = AeroAcousticsSimulator()
        self.binaural = BinauralSpatialAudio()

    def launch(
        self,
        velocity: float,
        launch_angle: float,
        rotation_speed: float = 100.0,
        shape_profile: str = "conical",
        observer_distance: float = 30.0,
        observer_heading_deg: float = 0.0,
        duration_sec: float = 2.5,
        include_aerodynamics: bool = True,
        include_acoustics: bool = True,
    ) -> LaunchExperienceResult:
        """
        执行一次虚拟发射体验。

        Args:
            velocity: 初始速度 m/s (>0)
            launch_angle: 发射角 rad (0 ~ π/2)
            rotation_speed: 箭体转速 rad/s
            shape_profile: 箭头形状 (conical/spherical/blunt/ogival)
            observer_distance: 观测距离 m
            observer_heading_deg: 观测者朝向角度 (°)，0 朝前方
            duration_sec: 音频总时长 s
            include_aerodynamics: 是否包含完整气动结果
            include_acoustics: 是否包含完整声学结果

        Returns:
            LaunchExperienceResult 含音频参数、弹道摘要、气动/声学结果
        """
        trajectory = self.aero_sim.calculate_trajectory(
            velocity, launch_angle, rotation_speed
        )

        peak_altitude = max((p["altitude"] for p in trajectory), default=0)
        final_range = trajectory[-1]["x"] if trajectory else 0
        flight_time = trajectory[-1]["time"] if trajectory else 0

        source_position = self._calculate_source_position(
            observer_distance, observer_heading_deg, peak_altitude
        )

        audio = self._build_launch_audio(
            velocity=velocity,
            rotation_speed=rotation_speed,
            shape_profile=shape_profile,
            distance=observer_distance,
            source_position=source_position,
            observer_heading_deg=observer_heading_deg,
            duration_sec=duration_sec,
        )

        audio["trajectory"] = {
            "peak_altitude": round(peak_altitude, 1),
            "estimated_range": round(final_range, 1),
            "flight_time": round(flight_time, 2),
            "point_count": len(trajectory),
            "launch_angle": launch_angle,
            "source_position_m": list(source_position),
        }

        aero_result = None
        if include_aerodynamics:
            aero_result = self.shape_sim.simulate_shape(
                velocity, shape_profile, 0.0, rotation_speed
            )

        ac_result = None
        if include_acoustics:
            ac_result = self.acoustics_sim.simulate(
                velocity, rotation_speed, observer_distance
            )

        return LaunchExperienceResult(
            audio=audio,
            trajectory_summary={
                "peak_altitude": round(peak_altitude, 1),
                "estimated_range": round(final_range, 1),
                "flight_time": round(flight_time, 2),
                "launch_angle": launch_angle,
                "initial_velocity": velocity,
            },
            aerodynamics=aero_result,
            acoustics=ac_result,
        )

    def _calculate_source_position(
        self,
        observer_distance: float,
        observer_heading_deg: float,
        peak_altitude: float,
    ) -> Tuple[float, float, float]:
        """
        根据观测者朝向计算声源位置（右手坐标系）。
        0° 朝 +X 方向，逆时针为正。
        返回世界坐标系中的声源位置，BinauralSpatialAudio 会处理观察者朝向。
        """
        x = observer_distance
        y = 0.0
        z = peak_altitude * 0.3 + 1.5
        return (x, y, z)

    def _build_launch_audio(
        self,
        velocity: float,
        rotation_speed: float,
        shape_profile: str,
        distance: float,
        source_position: Tuple[float, float, float],
        observer_heading_deg: float = 0.0,
        duration_sec: float = 2.5,
    ) -> Dict:
        """构造音频合成参数，含双耳空间化。"""
        ac = self.acoustics_sim.simulate(velocity, rotation_speed, distance)
        waveform = self.WAVEFORM_BY_SHAPE.get(shape_profile, "sawtooth")

        vib_hz = 5.0 + 0.02 * max(20.0, min(300.0, 0.8 * velocity + 40))
        vib_depth = min(1.2, 0.15 + 0.004 * max(20.0, min(300.0, 0.8 * velocity + 40)))

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

    def get_shape_timbres(self) -> Dict[str, str]:
        """获取各形状的音色描述"""
        return dict(_SHAPE_TIMBRE)

    def get_available_shapes(self) -> List[str]:
        """获取可用形状列表"""
        return list(_SHAPE_TIMBRE.keys())

    def estimate_trajectory(
        self, velocity: float, launch_angle: float, rotation_speed: float = 0.0
    ) -> Dict:
        """快速估算弹道参数（无需完整音频合成）"""
        trajectory = self.aero_sim.calculate_trajectory(
            velocity, launch_angle, rotation_speed
        )
        peak_altitude = max((p["altitude"] for p in trajectory), default=0)
        final_range = trajectory[-1]["x"] if trajectory else 0
        flight_time = trajectory[-1]["time"] if trajectory else 0
        return {
            "peak_altitude": round(peak_altitude, 1),
            "estimated_range": round(final_range, 1),
            "flight_time": round(flight_time, 2),
            "point_count": len(trajectory),
            "trajectory_points": trajectory,
        }
