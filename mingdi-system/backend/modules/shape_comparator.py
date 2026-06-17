"""
形状对比模块 (shape_comparator)
独立封装古代鸣镝不同形状（锥形/球形/钝头/尖拱形）的空气动力学与声学对比仿真。

职责：
- 多形状气动参数批量仿真
- 形状间性能差异量化对比
- 数据质量评估（实验测定 vs 理论推断）
- 对比结果结构化输出

依赖：physics.shape_acoustics.ShapeAwareAeroSimulator
"""
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

from ..physics import ShapeAwareAeroSimulator, SHAPE_PROFILES, get_shape_data_quality

logger = logging.getLogger(__name__)


@dataclass
class ShapeComparisonRequest:
    velocity: float
    shapes: List[str] = None
    angle_of_attack: float = 0.0
    rotation_speed: float = 0.0
    include_data_quality: bool = True


@dataclass
class ShapeComparisonResult:
    velocity: float
    angle_of_attack: float
    rotation_speed: float
    results: Dict[str, dict]
    ranking: Dict[str, Dict[str, float]]
    data_quality_summary: Dict[str, dict]

    def to_dict(self) -> dict:
        return {
            "velocity": self.velocity,
            "angle_of_attack": self.angle_of_attack,
            "rotation_speed": self.rotation_speed,
            "comparison": self.results,
            "ranking": self.ranking,
            "data_quality": self.data_quality_summary,
        }


class ShapeComparator:
    """
    形状对比仿真器，封装多鸣镝形状的气动/声学对比分析。

    Example:
        comparator = ShapeComparator()
        result = comparator.compare(
            velocity=65.0,
            shapes=["conical", "spherical", "blunt", "ogival"],
            angle_of_attack=0.1,
            rotation_speed=100.0
        )
        print(result.ranking["drag_coefficient"])  # 按阻力系数排序
    """

    _RANK_KEYS = [
        "drag_coefficient", "lift_coefficient",
        "drag_force", "lift_force",
        "reynolds_number", "mach_number",
    ]

    def __init__(self, rho: float = None, mu: float = None, c0: float = None):
        self._sim = ShapeAwareAeroSimulator(rho=rho, mu=mu, c0=c0)
        self.available_shapes = list(SHAPE_PROFILES.keys())

    def compare(
        self,
        velocity: float,
        shapes: List[str] = None,
        angle_of_attack: float = 0.0,
        rotation_speed: float = 0.0,
        include_data_quality: bool = True,
    ) -> ShapeComparisonResult:
        """
        对比多个鸣镝形状的气动性能。

        Args:
            velocity: 飞行速度 m/s (>0)
            shapes: 要对比的形状列表，None 表示全部
            angle_of_attack: 攻角 rad
            rotation_speed: 转速 rad/s
            include_data_quality: 是否包含数据质量评估

        Returns:
            ShapeComparisonResult 结构化对比结果
        """
        if shapes is None:
            shapes = self.available_shapes

        valid_shapes = []
        for s in shapes:
            if s in SHAPE_PROFILES:
                valid_shapes.append(s)
            else:
                logger.warning("[ShapeComparator] 未知形状 %s，跳过", s)

        if not valid_shapes:
            raise ValueError(f"没有有效的形状可对比，可用形状: {self.available_shapes}")

        results = {}
        for shape in valid_shapes:
            results[shape] = self._sim.simulate_shape(
                velocity=velocity,
                shape_profile=shape,
                angle_of_attack=angle_of_attack,
                rotation_speed=rotation_speed,
            )

        ranking = self._build_ranking(results)
        data_quality = {}
        if include_data_quality:
            for shape in valid_shapes:
                data_quality[shape] = get_shape_data_quality(shape)

        return ShapeComparisonResult(
            velocity=velocity,
            angle_of_attack=angle_of_attack,
            rotation_speed=rotation_speed,
            results=results,
            ranking=ranking,
            data_quality_summary=data_quality,
        )

    def _build_ranking(self, results: Dict[str, dict]) -> Dict[str, Dict[str, float]]:
        """
        按各项指标对形状排序，返回 {metric: {shape: rank}}。
        rank 越小越好（1 = 最优）。
        """
        ranking = {}
        for key in self._RANK_KEYS:
            values = []
            for shape, r in results.items():
                if key in r:
                    values.append((shape, r[key]))
            if not values:
                continue

            if key in ("drag_coefficient", "drag_force"):
                values.sort(key=lambda x: x[1])
            else:
                values.sort(key=lambda x: x[1], reverse=True)

            ranking[key] = {shape: i + 1 for i, (shape, _) in enumerate(values)}

        summary = {}
        for shape in results:
            ranks = []
            for metric_ranks in ranking.values():
                if shape in metric_ranks:
                    ranks.append(metric_ranks[shape])
            if ranks:
                summary[shape] = sum(ranks) / len(ranks)

        ranking["overall"] = {
            k: v for k, v in sorted(summary.items(), key=lambda x: x[1])
        }
        return ranking

    def get_shape_profiles(self) -> Dict:
        """获取所有形状的参数配置与数据质量"""
        shape_quality = {s: get_shape_data_quality(s) for s in SHAPE_PROFILES}
        return {
            "shapes": list(SHAPE_PROFILES.keys()),
            "profiles": dict(SHAPE_PROFILES),
            "data_quality": shape_quality,
            "provenance_scale": [
                "windtunnel (实验测定)",
                "archaeology (考古实物)",
                "literature (文献)",
                "fallback (理论推断)",
            ],
        }

    def get_shape_data_quality(self, shape_name: str) -> Dict:
        """获取单个形状的数据质量评估"""
        return get_shape_data_quality(shape_name)
