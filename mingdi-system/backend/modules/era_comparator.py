"""
跨时代声学对比模块 (era_comparator)
独立封装古代鸣镝（汉代）与现代体育口哨（FOX 40等）的跨时代声学对比分析。

职责：
- 鸣镝 vs 现代口哨 声学参数对比
- 发声机制差异量化（腔体共鸣 vs 射流-边棱音）
- 标准化参考锚定（FOX 40 Classic 四认证）
- 频率/SPL/传播距离/谐波结构 四维对比

依赖：
- physics.aerodynamics.AeroDynamicsSimulator
- physics.aeroacoustics.AeroAcousticsSimulator
- physics.shape_acoustics.ModernWhistleAcousticSimulator
"""
import logging
from typing import Dict, Optional
from dataclasses import dataclass

from ..config import settings
from ..physics import (
    AeroDynamicsSimulator,
    AeroAcousticsSimulator,
    ModernWhistleAcousticSimulator,
    ShapeAwareAeroSimulator,
    get_shape_data_quality,
)
from ..config_loader import list_modern_whistle_models, get_modern_whistle_defaults

logger = logging.getLogger(__name__)


@dataclass
class EraComparisonRequest:
    velocity: float
    rotation_speed: float = 100.0
    distance: float = 1.0
    modern_model: str = "fox40_classic"
    modern_whistle_length: Optional[float] = None
    modern_whistle_diameter: Optional[float] = None
    mingdi_shape: str = "conical"


@dataclass
class EraComparisonResult:
    velocity: float
    rotation_speed: float
    observer_distance: float
    mingdi: dict
    modern_whistle: dict
    comparison: dict
    standardization_note: str

    def to_dict(self) -> dict:
        return {
            "velocity": self.velocity,
            "rotation_speed": self.rotation_speed,
            "observer_distance": self.observer_distance,
            "standardization_note": self.standardization_note,
            "mingdi": self.mingdi,
            "modern_whistle": self.modern_whistle,
            "comparison": self.comparison,
        }


class EraComparator:
    """
    跨时代声学对比器，封装古代鸣镝与现代体育口哨的对比分析。

    Example:
        comparator = EraComparator()
        result = comparator.compare(
            velocity=65.0,
            modern_model="fox40_classic",
            distance=10.0
        )
        print(result.comparison["key_insight"])
    """

    ERA_GAP_YEARS = 2200

    def __init__(self):
        self.mingdi_aero = ShapeAwareAeroSimulator()
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
        mingdi_shape: str = "conical",
    ) -> EraComparisonResult:
        """
        执行跨时代声学对比。

        Args:
            velocity: 飞行速度 m/s (>0)
            rotation_speed: 转速 rad/s
            distance: 观测距离 m
            modern_model: 现代口哨型号，默认 fox40_classic
            modern_whistle_length: 手动覆盖口哨长度 m
            modern_whistle_diameter: 手动覆盖口哨直径 m
            mingdi_shape: 鸣镝形状，默认锥形

        Returns:
            EraComparisonResult 结构化对比结果
        """
        from ..physics.shape_acoustics import SHAPE_PROFILES

        aero_result = self.mingdi_aero.simulate_shape(
            velocity, mingdi_shape, 0.0, rotation_speed
        )

        sp = SHAPE_PROFILES.get(mingdi_shape, SHAPE_PROFILES["conical"])
        strouhal = sp.get("whistle_strouhal", 0.2)
        cavity_coupling = sp.get("whistle_cavity_coupling", 0.6)
        efficiency = sp.get("whistle_efficiency", 0.8)

        self.mingdi_acoustic.strouhal_number = strouhal
        base_freq = self.mingdi_acoustic.calculate_whistle_frequency(velocity, rotation_speed)
        shape_freq = base_freq * (1.0 + 0.15 * (cavity_coupling - 0.6))

        base_power = self.mingdi_acoustic.calculate_sound_power(velocity, rotation_speed)
        shape_power = base_power * efficiency

        spl, source_breakdown = self.mingdi_acoustic.calculate_spl_fwh(
            velocity, rotation_speed, distance, angle=0.0
        )
        shape_spl = self.mingdi_acoustic.spl_from_power(shape_power, distance)
        final_spl = 0.6 * spl + 0.4 * shape_spl

        propagation_dist = self.mingdi_acoustic.calculate_propagation_distance(final_spl)
        directivity = self.mingdi_acoustic.calculate_directivity_pattern()
        re = self.mingdi_acoustic.rho * velocity * self.mingdi_acoustic.whistle_d / settings.air_viscosity

        mingdi_result = {
            "whistle_frequency": round(shape_freq, 1),
            "sound_pressure_level": round(final_spl, 1),
            "sound_pressure_level_lighthill": round(shape_spl, 1),
            "sound_pressure_level_fwh": round(spl, 1),
            "propagation_distance": round(propagation_dist, 1),
            "directivity_pattern": directivity,
            "strouhal_number": round(strouhal, 3),
            "source_breakdown": source_breakdown,
            "shape_profile": mingdi_shape,
        }

        modern_result = self.modern_whistle.simulate_modern_whistle(
            velocity,
            whistle_length=modern_whistle_length,
            whistle_diameter=modern_whistle_diameter,
            model_name=modern_model,
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

        mingdi_quality = get_shape_data_quality(mingdi_shape)

        standardization_note = (
            "现代口哨参数基于FOX 40 Classic（FIFA/FIBA认证裁判哨）实物测量。"
            "鸣镝锥形参数基于满城汉墓出土实物+风洞实验校准。"
            + (f" 注意: {'; '.join(mingdi_quality['warnings'])}" if mingdi_quality["warnings"] else "")
        )

        mingdi_dict = {
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
        }

        modern_dict = {
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
            "mouthpiece_type": modern_result.get("mouthpiece_type"),
            "chamber_count": modern_result.get("chamber_count"),
            "standard_reference": modern_result.get("standard_reference"),
        }

        comparison_dict = {
            "frequency_ratio_mingdi_to_modern": round(freq_ratio, 3),
            "spl_difference_db": round(spl_diff, 1),
            "propagation_distance_ratio": round(m_range / w_range, 2) if w_range > 0 else 0,
            "dominant_harmonic_count_mingdi": len(m_harmonics),
            "dominant_harmonic_count_modern": len(w_harmonics),
            "era_gap_years": self.ERA_GAP_YEARS,
            "key_insight": self._generate_insight(freq_ratio, spl_diff, m_freq, w_freq),
        }

        return EraComparisonResult(
            velocity=velocity,
            rotation_speed=rotation_speed,
            observer_distance=distance,
            mingdi=mingdi_dict,
            modern_whistle=modern_dict,
            comparison=comparison_dict,
            standardization_note=standardization_note,
        )

    def _generate_insight(self, freq_ratio: float, spl_diff: float, m_freq: float, w_freq: float) -> str:
        """根据频率比与SPL差异生成自动洞察文案"""
        if freq_ratio < 0.5:
            return f"鸣镝频率({m_freq:.0f}Hz)远低于现代口哨({w_freq:.0f}Hz)，古代哨音偏深沉"
        elif freq_ratio < 1.0:
            return f"鸣镝频率({m_freq:.0f}Hz)低于现代口哨({w_freq:.0f}Hz)，但音色更具战争威慑感"
        elif freq_ratio < 1.5:
            return f"鸣镝与现代口哨频率接近({m_freq:.0f}Hz vs {w_freq:.0f}Hz)，但发声机制截然不同"
        else:
            return f"鸣镝频率({m_freq:.0f}Hz)高于现代口哨({w_freq:.0f}Hz)，哨音尖锐刺耳"

    def list_available_models(self) -> Dict:
        """获取可用现代口哨型号列表"""
        return {
            "default_model": "fox40_classic",
            "models": list_modern_whistle_models(),
            "certifications": ["FIFA", "FIBA", "FINA", "IOC", "NCAA"],
        }

    def get_model_defaults(self, model_name: str = None) -> Dict:
        """获取指定型号的标准参数"""
        return get_modern_whistle_defaults(model_name)
