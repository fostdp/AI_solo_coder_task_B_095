"""
声场叠加模块 (field_superposer)
独立封装多支响箭齐射时的声场叠加模拟，支持 NumPy 向量化 + CuPy GPU 加速。

职责：
- 多声源声场叠加（相干/非相干叠加）
- 干涉图案识别（建设性/破坏性干涉）
- NumPy 广播张量向量化加速
- CuPy CUDA 透明 fallback
- 预设阵型生成（横排/楔形/弧形/散布/军阵/埋伏/斥候/单箭）
- 双耳空间音频合成参数

依赖：physics.volley_simulation 中的核心实现
"""
import logging
import math
import random
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

from ..physics.volley_simulation import (
    VolleySimulation,
    VolleyArrowConfig,
    AudioSynthesisParams,
    create_preset_volley,
    _SHAPE_TIMBRE,
    _WAVETABLE_HARMONIC_RATIOS,
    _WAVETABLE_HARMONIC_GAINS,
)

logger = logging.getLogger(__name__)


@dataclass
class SuperpositionRequest:
    arrows: List[Dict]
    grid_size: int = 40
    grid_extent: float = 30.0
    observer_height: float = 1.5
    interference_threshold_db: float = 3.0
    listener_position: Tuple[float, float, float] = (0.0, 0.0, 1.5)
    listener_heading_deg: float = 0.0
    duration_sec: float = 2.5
    backend: str = "numpy"
    binaural: bool = True


@dataclass
class SuperpositionResult:
    arrow_count: int
    grid_size: int
    grid_extent_m: float
    acoustic_backend: str
    computation_ms: float
    performance_hint: Optional[str]
    spl_grid: List[List[float]]
    frequency_grid: List[List[float]]
    x_axis_m: List[float]
    y_axis_m: List[float]
    interference_regions: List[Dict]
    total_acoustic_power_w: float
    sound_centroid_m: List[float]
    arrow_sources: List[Dict]
    centroid_db: float
    audio_synthesis: Optional[Dict]

    def to_dict(self) -> dict:
        return {
            "arrow_count": self.arrow_count,
            "grid_size": self.grid_size,
            "grid_extent_m": self.grid_extent_m,
            "acoustic_backend": self.acoustic_backend,
            "computation_ms": self.computation_ms,
            "performance_hint": self.performance_hint,
            "spl_grid": self.spl_grid,
            "frequency_grid": self.frequency_grid,
            "x_axis_m": self.x_axis_m,
            "y_axis_m": self.y_axis_m,
            "interference_regions": self.interference_regions,
            "total_acoustic_power_w": self.total_acoustic_power_w,
            "sound_centroid_m": self.sound_centroid_m,
            "arrow_sources": self.arrow_sources,
            "centroid_db": self.centroid_db,
            "audio_synthesis": self.audio_synthesis,
        }


class FieldSuperposer:
    """
    声场叠加仿真器，封装多声源相干叠加与干涉分析。

    自动检测 CUDA/CuPy，优先使用 GPU 加速；不可用时透明回退到 NumPy CPU。

    Example:
        superposer = FieldSuperposer(backend="auto")
        arrows = superposer.create_preset_arrows("marching_10", velocity=65.0)
        result = superposer.superpose(arrows, grid_size=40, grid_extent=30.0)
        print(result.interference_regions)
    """

    PRESET_PATTERNS = ["line", "wedge", "arc", "random",
                       "marching_10", "ambush_20", "scouts_3", "single"]

    def __init__(self, backend: str = "auto"):
        self.backend = backend
        self._sim = VolleySimulation(backend=backend)
        self._shape_cycle = ["conical", "spherical", "blunt", "ogival"]

    def superpose(
        self,
        arrows: List[VolleyArrowConfig],
        grid_size: int = 40,
        grid_extent: float = 30.0,
        observer_height: float = 1.5,
        interference_threshold_db: float = 3.0,
        listener_position: Tuple[float, float, float] = (0.0, 0.0, 1.5),
        listener_heading_deg: float = 0.0,
        duration_sec: float = 2.5,
        binaural: bool = True,
    ) -> SuperpositionResult:
        """
        执行多声源声场叠加仿真。

        Args:
            arrows: 箭支配置列表
            grid_size: 网格分辨率 N×N
            grid_extent: 网格物理范围 (m)
            observer_height: 观测平面高度 (m)
            interference_threshold_db: 干涉识别阈值 (dB)
            listener_position: 听者坐标 (x, y, z)
            listener_heading_deg: 听者朝向 (°)，0 朝 +x
            duration_sec: 音频合成总时长
            binaural: 是否启用双耳空间音频

        Returns:
            SuperpositionResult 结构化结果
        """
        result = self._sim.simulate_volley(
            arrows=arrows,
            grid_size=grid_size,
            grid_extent=grid_extent,
            observer_height=observer_height,
            interference_threshold_db=interference_threshold_db,
        )

        source_position = result.get("sound_centroid_m")
        if source_position and len(source_position) >= 2:
            sp = (source_position[0], source_position[1], float(listener_position[2]))
        else:
            sp = (float(listener_position[0]) + 5.0,
                  float(listener_position[1]),
                  float(listener_position[2]))

        audio_params = self._sim.get_audio_synthesis_params(
            volley_result=result,
            listener_position=listener_position,
            listener_heading_deg=listener_heading_deg,
            duration_sec=duration_sec,
        )

        audio_dict = audio_params.calculate(
            binaural=binaural,
            source_position=sp,
            observer_heading_deg=listener_heading_deg,
        ) if binaural else audio_params.calculate(binaural=False)

        result["audio_synthesis"] = audio_dict

        return SuperpositionResult(
            arrow_count=result["arrow_count"],
            grid_size=result["grid_size"],
            grid_extent_m=result["grid_extent_m"],
            acoustic_backend=result["acoustic_backend"],
            computation_ms=result["computation_ms"],
            performance_hint=result.get("performance_hint"),
            spl_grid=result["spl_grid"],
            frequency_grid=result["frequency_grid"],
            x_axis_m=result.get("x_axis_m", []),
            y_axis_m=result.get("y_axis_m", []),
            interference_regions=result["interference_regions"],
            total_acoustic_power_w=result["total_acoustic_power_w"],
            sound_centroid_m=result["sound_centroid_m"],
            arrow_sources=result["arrow_sources"],
            centroid_db=result["centroid_db"],
            audio_synthesis=audio_dict,
        )

    def create_preset_arrows(
        self,
        pattern: str,
        count: int = 5,
        velocity: float = 65.0,
        rotation_speed: float = 100.0,
        spacing: float = 5.0,
    ) -> List[VolleyArrowConfig]:
        """
        创建预设阵型的箭支配置。

        Args:
            pattern: 阵型名，参见 PRESET_PATTERNS
            count: 箭支数量（仅 line/wedge/arc/random 有效）
            velocity: 飞行速度 m/s
            rotation_speed: 转速 rad/s
            spacing: 间距 m

        Returns:
            List[VolleyArrowConfig] 箭支配置列表
        """
        known_presets = ("marching_10", "ambush_20", "scouts_3", "single")
        if pattern in known_presets:
            preset_arrows = create_preset_volley(pattern)
            for a in preset_arrows:
                a.velocity = velocity
                a.rotation_speed = rotation_speed
            return preset_arrows

        from ..physics import AeroAcousticsSimulator
        ac_sim = AeroAcousticsSimulator()
        ac_result = ac_sim.simulate(velocity, rotation_speed, 1.0)

        arrows = []
        if pattern == "line":
            for i in range(count):
                x = (i - count / 2) * spacing
                arrows.append(VolleyArrowConfig(
                    id=i + 1, x=x, y=0.0, z=1.5,
                    velocity=velocity, rotation_speed=rotation_speed,
                    shape_profile=self._shape_cycle[i % 4],
                    spl_1m=ac_result["sound_pressure_level"],
                    frequency=ac_result["whistle_frequency"],
                ))
        elif pattern == "wedge":
            for i in range(count):
                row = i // 2
                side = 1 if i % 2 == 0 else -1
                x = side * (row + 1) * spacing * 0.5
                y = row * spacing
                arrows.append(VolleyArrowConfig(
                    id=i + 1, x=x, y=y, z=1.5,
                    velocity=velocity, rotation_speed=rotation_speed,
                    shape_profile=self._shape_cycle[i % 4],
                    spl_1m=ac_result["sound_pressure_level"],
                    frequency=ac_result["whistle_frequency"],
                ))
        elif pattern == "arc":
            radius = max(count * spacing / (2 * math.pi), spacing)
            for i in range(count):
                angle = math.pi * (i / max(count - 1, 1) - 0.5)
                x = radius * math.sin(angle)
                y = radius * (1 - math.cos(angle))
                arrows.append(VolleyArrowConfig(
                    id=i + 1, x=round(x, 2), y=round(y, 2), z=1.6,
                    velocity=velocity + random.uniform(-2, 2),
                    rotation_speed=rotation_speed,
                    shape_profile=self._shape_cycle[i % 4],
                    spl_1m=ac_result["sound_pressure_level"],
                    frequency=ac_result["whistle_frequency"],
                ))
        else:
            for i in range(count):
                arrows.append(VolleyArrowConfig(
                    id=i + 1,
                    x=round(random.uniform(-count * spacing / 2, count * spacing / 2), 2),
                    y=round(random.uniform(-spacing, spacing), 2),
                    z=1.5,
                    velocity=velocity + random.uniform(-5, 5),
                    rotation_speed=rotation_speed + random.uniform(-10, 10),
                    shape_profile=self._shape_cycle[i % 4],
                    spl_1m=ac_result["sound_pressure_level"],
                    frequency=ac_result["whistle_frequency"],
                ))

        return arrows

    def get_available_patterns(self) -> List[str]:
        """获取所有可用阵型"""
        return list(self.PRESET_PATTERNS)

    def get_backend_info(self) -> Dict:
        """获取后端加速信息"""
        from ..physics.volley_simulation import _HAS_CUPY
        return {
            "current_backend": self._sim.backend_name,
            "cupy_available": _HAS_CUPY,
            "supported_backends": ["numpy", "cupy"],
        }

    def estimate_computation_time(self, arrow_count: int, grid_size: int) -> float:
        """
        估算计算时间 (ms)。
        基于基准：20箭×40²网格 ≈ 200ms (NumPy) / 40ms (CuPy)
        """
        complexity = arrow_count * grid_size * grid_size
        if self._sim.backend_name == "cupy":
            return complexity * 0.000025
        return complexity * 0.000125
