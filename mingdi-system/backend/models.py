from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class SensorData(BaseModel):
    arrow_id: str = Field(..., description="响箭唯一标识")
    timestamp: Optional[datetime] = None
    velocity: float = Field(..., gt=0, description="飞行速度 m/s")
    rotation_speed: float = Field(..., ge=0, description="转速 rad/s")
    whistle_frequency: float = Field(..., gt=0, description="哨音频率 Hz")
    sound_pressure_level: float = Field(..., description="声压级 dB")
    altitude: Optional[float] = Field(0.0, description="飞行高度 m")
    pitch: Optional[float] = Field(0.0, description="俯仰角 rad")
    yaw: Optional[float] = Field(0.0, description="偏航角 rad")


class AeroDynamicsResult(BaseModel):
    drag_force: float
    lift_force: float
    moment: float
    reynolds_number: float
    drag_coefficient: float
    lift_coefficient: float
    pressure_distribution: list[float]


class AeroAcousticsResult(BaseModel):
    whistle_frequency: float
    sound_pressure_level: float
    propagation_distance: float
    directivity_pattern: list[float]
    strouhal_number: float


class AlertMessage(BaseModel):
    arrow_id: str
    alert_type: str
    message: str
    timestamp: datetime
    severity: str
    current_value: float
    threshold: float


class FlightStatus(BaseModel):
    arrow_id: str
    timestamp: datetime
    velocity: float
    rotation_speed: float
    altitude: float
    whistle_frequency: float
    sound_pressure_level: float
    estimated_range: float
    is_alert: bool = False


class ShapeComparisonRequest(BaseModel):
    velocity: float = Field(..., gt=0, description="飞行速度 m/s")
    shapes: list[str] = Field(["conical", "spherical", "blunt", "ogival"], description="对比形状列表")
    angle_of_attack: float = Field(0.0, description="攻角 rad")
    rotation_speed: float = Field(0.0, description="转速 rad/s")


class VolleyArrowConfig(BaseModel):
    arrow_id: str = Field("volley-1", description="箭ID")
    velocity: float = Field(65.0, gt=0, description="速度 m/s")
    rotation_speed: float = Field(100.0, description="转速 rad/s")
    whistle_frequency: float = Field(1500.0, gt=0, description="哨音频率 Hz")
    sound_pressure_level: float = Field(85.0, description="声压级 dB")
    position: list[float] = Field([0.0, 0.0], description="箭位置 [x, y] m")


class VolleySimulationRequest(BaseModel):
    arrows: list[VolleyArrowConfig] = Field(..., min_length=1, max_length=20, description="齐射箭列表")
    grid_size: int = Field(40, ge=10, le=80, description="栅格大小")
    grid_spacing: float = Field(2.0, gt=0, description="栅格间距 m")
    observer_position: list[float] = Field([0.0, 50.0], description="观测者位置 [x, y] m")


class LaunchExperienceRequest(BaseModel):
    velocity: float = Field(65.0, gt=0, le=200, description="初始速度 m/s")
    launch_angle: float = Field(0.3, ge=0, le=1.5, description="发射角 rad")
    rotation_speed: float = Field(100.0, ge=0, description="初始转速 rad/s")
    shape_profile: str = Field("conical", description="箭头形状")
    observer_distance: float = Field(10.0, gt=0, description="观测距离 m")
