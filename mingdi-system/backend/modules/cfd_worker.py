"""
CFD 计算独立 Worker 进程模块 (cfd_worker)
将计算密集型的 CFD（计算流体动力学）仿真从主 FastAPI 进程中剥离，
避免阻塞事件循环，支持异步任务提交与结果查询。

职责：
- SST k-ω 湍流模型计算（独立进程）
- 雷诺平均 Navier-Stokes (RANS) 简化求解
- 边界层/激波/湍流特性计算
- 异步任务队列管理
- Worker 进程池调度
- 任务状态跟踪与结果缓存

依赖：
- physics.aerodynamics.SSTKOmegaModel
- physics.aerodynamics.AeroDynamicsSimulator
- multiprocessing.Pool / Process
"""
import logging
import time
import uuid
import threading
from enum import Enum
from typing import Dict, Optional, Any, Callable, List
from dataclasses import dataclass, field
from multiprocessing import Pool, cpu_count, get_context

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

logger = logging.getLogger(__name__)


class CFDJobStatus(str, Enum):
    """CFD 任务状态枚举"""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class CFDJob:
    """CFD 计算任务封装"""
    job_id: str
    job_type: str
    params: Dict[str, Any]
    status: CFDJobStatus = CFDJobStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    progress: float = 0.0
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    priority: int = 5

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "status": self.status.value,
            "progress": self.progress,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "wait_time_ms": round((time.time() - self.created_at) * 1000, 1) if self.status in (CFDJobStatus.PENDING, CFDJobStatus.QUEUED) else None,
            "execution_ms": round((self.completed_at - self.started_at) * 1000, 1) if self.completed_at and self.started_at else None,
            "error": self.error,
            "result_summary": self._result_summary(),
        }

    def _result_summary(self) -> Optional[Dict]:
        if not self.result:
            return None
        return {
            "keys": list(self.result.keys()),
            "has_numpy_arrays": any(isinstance(v, (np.ndarray, list)) for v in self.result.values()) if _HAS_NUMPY else False,
        }


# ============================================================
# 进程池中执行的静态函数（必须顶层可 pickle）
# ============================================================

def _worker_run_cfd_job(job_type: str, params: Dict) -> Dict:
    """
    Worker 进程中实际执行 CFD 计算的函数。
    必须定义在模块顶层以支持 multiprocessing pickle。
    """
    import math
    from ..physics.aerodynamics import AeroDynamicsSimulator, SSTKOmegaModel
    from ..config import settings

    rho = params.get("rho", settings.air_density)
    mu = params.get("mu", settings.air_viscosity)
    c0 = params.get("c0", settings.speed_of_sound)

    if job_type == "sst_komega_turbulence":
        velocity = params["velocity"]
        length_scale = params.get("length_scale", settings.arrow_diameter)
        turbulence_intensity = params.get("turbulence_intensity", 0.05)

        sst = SSTKOmegaModel(rho=rho, mu=mu)
        result = sst.compute_turbulent_quantities(
            velocity=velocity,
            length_scale=length_scale,
            turbulence_intensity=turbulence_intensity,
        )
        result["reynolds_number"] = rho * velocity * length_scale / mu
        result["mach_number"] = velocity / c0
        return result

    elif job_type == "full_aerodynamics":
        velocity = params["velocity"]
        angle_of_attack = params.get("angle_of_attack", 0.0)
        rotation_speed = params.get("rotation_speed", 0.0)

        sim = AeroDynamicsSimulator()
        result = sim.simulate(velocity, angle_of_attack, rotation_speed)
        return result

    elif job_type == "trajectory_simulation":
        velocity = params["velocity"]
        launch_angle = params.get("launch_angle", 0.3)
        rotation_speed = params.get("rotation_speed", 0.0)
        time_step = params.get("time_step", 0.01)

        sim = AeroDynamicsSimulator()
        trajectory = sim.calculate_trajectory(
            velocity,
            launch_angle,
            rotation_speed,
        )
        return {
            "trajectory_points": trajectory,
            "point_count": len(trajectory),
            "peak_altitude": max((p["altitude"] for p in trajectory), default=0),
            "final_range": trajectory[-1]["x"] if trajectory else 0,
            "flight_time": trajectory[-1]["time"] if trajectory else 0,
        }

    elif job_type == "boundary_layer_profile":
        velocity = params["velocity"]
        length_scale = params.get("length_scale", settings.arrow_length)
        num_points = params.get("num_points", 50)

        re = rho * velocity * length_scale / mu
        if re < 5e5:
            delta = 4.92 * length_scale / math.sqrt(re)
            cf = 1.328 / math.sqrt(re)
            profile_type = "laminar"
        else:
            delta = 0.37 * length_scale / (re ** 0.2)
            cf = 0.074 / (re ** 0.2)
            profile_type = "turbulent"

        y_normalized = np.linspace(0, 1, num_points) if _HAS_NUMPY else [i / num_points for i in range(num_points)]
        u_over_U = []
        for y_plus in y_normalized:
            if profile_type == "laminar":
                u_over_U.append(1.5 * y_plus - 0.5 * y_plus ** 3)
            else:
                u_over_U.append(y_plus ** (1/7) if y_plus <= 1 else 1.0)

        return {
            "reynolds_number": re,
            "boundary_layer_thickness_m": delta,
            "skin_friction_coefficient": cf,
            "profile_type": profile_type,
            "y_normalized": list(y_normalized),
            "u_over_U": u_over_U,
            "length_scale_m": length_scale,
        }

    elif job_type == "shock_wave_analysis":
        velocity = params["velocity"]
        mach = velocity / c0

        if mach < 0.8:
            return {
                "mach_number": mach,
                "flow_regime": "subsonic",
                "has_shock": False,
                "note": "马赫数 < 0.8，无激波",
            }
        elif mach < 1.2:
            regime = "transonic"
            shock_strength = (mach - 0.8) / 0.4
        else:
            regime = "supersonic"
            shock_strength = min(1.0, 0.5 + 0.5 * (mach - 1.2))

        beta = math.sqrt(abs(mach ** 2 - 1)) if mach >= 1 else math.sqrt(abs(1 - mach ** 2))
        mach_angle = math.degrees(math.asin(1 / mach)) if mach > 1 else 90.0

        return {
            "mach_number": mach,
            "flow_regime": regime,
            "has_shock": mach >= 0.8,
            "shock_strength": round(shock_strength, 3),
            "mach_angle_deg": round(mach_angle, 1),
            "prandtl_glauert_factor": round(beta, 3),
            "wave_drag_estimate_db": round(10 * math.log10(1 + shock_strength * 5), 1),
        }

    else:
        raise ValueError(f"未知 CFD 任务类型: {job_type}")


# ============================================================
# CFD Worker 主类
# ============================================================

class CFDWorker:
    """
    CFD 计算 Worker 管理器，维护独立进程池执行计算密集型任务。

    Example:
        worker = CFDWorker(pool_size=2)
        worker.start()

        job_id = worker.submit_job(
            job_type="sst_komega_turbulence",
            params={"velocity": 65.0},
            callback=lambda job: print(f"任务 {job.job_id} 完成")
        )

        time.sleep(0.5)
        result = worker.get_job_result(job_id)
        worker.stop()
    """

    VALID_JOB_TYPES = [
        "sst_komega_turbulence",
        "full_aerodynamics",
        "trajectory_simulation",
        "boundary_layer_profile",
        "shock_wave_analysis",
    ]

    def __init__(self, pool_size: int = None, use_processes: bool = True):
        """
        Args:
            pool_size: 进程池大小，默认 = min(CPU核心数-1, 4)
            use_processes: True 使用多进程，False 使用多线程（调试用）
        """
        if pool_size is None:
            try:
                pool_size = max(1, min(cpu_count() - 1, 4))
            except Exception:
                pool_size = 2

        self.pool_size = pool_size
        self.use_processes = use_processes

        self._pool: Optional[Pool] = None
        self._jobs: Dict[str, CFDJob] = {}
        self._callbacks: Dict[str, Callable[[CFDJob], None]] = {}
        self._futures: Dict[str, Any] = {}
        self._lock = threading.RLock()
        self._monitor_thread: Optional[threading.Thread] = None
        self._running = False

        logger.info("[CFDWorker] 初始化完成，池大小=%d, 多进程=%s",
                    pool_size, use_processes)

    # ------------------------------
    # 生命周期管理
    # ------------------------------

    def start(self) -> None:
        """启动 Worker 进程池与监控线程"""
        if self._running:
            logger.warning("[CFDWorker] 已经启动，忽略重复 start()")
            return

        logger.info("[CFDWorker] 启动进程池，大小=%d", self.pool_size)

        if self.use_processes:
            ctx = get_context("spawn")
            self._pool = ctx.Pool(processes=self.pool_size)
        else:
            self._pool = None

        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def stop(self, wait: bool = True) -> None:
        """停止 Worker 进程池"""
        logger.info("[CFDWorker] 停止中...")
        self._running = False

        if self._monitor_thread:
            self._monitor_thread.join(timeout=2.0)
            self._monitor_thread = None

        if self._pool:
            if wait:
                self._pool.close()
                self._pool.join()
            else:
                self._pool.terminate()
            self._pool = None

        logger.info("[CFDWorker] 已停止")

    # ------------------------------
    # 任务提交
    # ------------------------------

    def submit_job(
        self,
        job_type: str,
        params: Dict[str, Any],
        callback: Optional[Callable[[CFDJob], None]] = None,
        priority: int = 5,
    ) -> str:
        """
        提交一个 CFD 计算任务。

        Args:
            job_type: 任务类型，参见 VALID_JOB_TYPES
            params: 任务参数字典
            callback: 任务完成回调函数
            priority: 优先级 1-10，1 最高

        Returns:
            job_id: 任务唯一标识符
        """
        if job_type not in self.VALID_JOB_TYPES:
            raise ValueError(
                f"无效任务类型 '{job_type}'，可用类型: {self.VALID_JOB_TYPES}"
            )

        if not self._running:
            logger.warning("[CFDWorker] 未启动，先自动启动")
            self.start()

        job_id = f"cfd-{uuid.uuid4().hex[:12]}"

        with self._lock:
            job = CFDJob(
                job_id=job_id,
                job_type=job_type,
                params=params,
                status=CFDJobStatus.QUEUED,
                priority=priority,
            )
            self._jobs[job_id] = job
            if callback:
                self._callbacks[job_id] = callback

        logger.info("[CFDWorker] 提交任务 %s (type=%s, priority=%d)",
                    job_id, job_type, priority)

        if self.use_processes and self._pool:
            future = self._pool.apply_async(
                _worker_run_cfd_job,
                args=(job_type, params),
                callback=lambda r, jid=job_id: self._on_job_success(jid, r),
                error_callback=lambda e, jid=job_id: self._on_job_failure(jid, e),
            )
            with self._lock:
                self._futures[job_id] = future
                self._jobs[job_id].status = CFDJobStatus.RUNNING
                self._jobs[job_id].started_at = time.time()
        else:
            threading.Thread(
                target=self._run_job_sync,
                args=(job_id, job_type, params),
                daemon=True,
            ).start()

        return job_id

    def _run_job_sync(self, job_id: str, job_type: str, params: Dict) -> None:
        """同步执行任务（多线程模式）"""
        try:
            with self._lock:
                self._jobs[job_id].status = CFDJobStatus.RUNNING
                self._jobs[job_id].started_at = time.time()

            result = _worker_run_cfd_job(job_type, params)
            self._on_job_success(job_id, result)
        except Exception as e:
            self._on_job_failure(job_id, e)

    # ------------------------------
    # 任务结果处理
    # ------------------------------

    def _on_job_success(self, job_id: str, result: Dict) -> None:
        """任务成功回调"""
        with self._lock:
            if job_id not in self._jobs:
                return
            job = self._jobs[job_id]
            job.status = CFDJobStatus.COMPLETED
            job.result = result
            job.progress = 1.0
            job.completed_at = time.time()
            callback = self._callbacks.pop(job_id, None)
            self._futures.pop(job_id, None)

        logger.info("[CFDWorker] 任务 %s 完成，耗时 %.1f ms",
                    job_id, (job.completed_at - job.started_at) * 1000)

        if callback:
            try:
                callback(job)
            except Exception as e:
                logger.error("[CFDWorker] 任务 %s 回调执行失败: %s", job_id, e)

    def _on_job_failure(self, job_id: str, error: Exception) -> None:
        """任务失败回调"""
        with self._lock:
            if job_id not in self._jobs:
                return
            job = self._jobs[job_id]
            job.status = CFDJobStatus.FAILED
            job.error = str(error)
            job.completed_at = time.time()
            callback = self._callbacks.pop(job_id, None)
            self._futures.pop(job_id, None)

        logger.error("[CFDWorker] 任务 %s 失败: %s", job_id, error)

        if callback:
            try:
                callback(job)
            except Exception as e:
                logger.error("[CFDWorker] 任务 %s 错误回调执行失败: %s", job_id, e)

    # ------------------------------
    # 任务查询
    # ------------------------------

    def get_job_status(self, job_id: str) -> Optional[CFDJob]:
        """查询任务状态"""
        with self._lock:
            return self._jobs.get(job_id)

    def get_job_result(self, job_id: str, timeout: float = 0.0) -> Optional[CFDJob]:
        """
        等待并获取任务结果。

        Args:
            job_id: 任务 ID
            timeout: 等待超时秒数，0 表示不等待

        Returns:
            CFDJob 任务对象，超时返回 None
        """
        if timeout > 0:
            start = time.time()
            while time.time() - start < timeout:
                with self._lock:
                    job = self._jobs.get(job_id)
                    if job and job.status in (CFDJobStatus.COMPLETED, CFDJobStatus.FAILED):
                        return job
                time.sleep(0.01)

        with self._lock:
            return self._jobs.get(job_id)

    def cancel_job(self, job_id: str) -> bool:
        """取消任务（仅排队中可取消）"""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status not in (CFDJobStatus.PENDING, CFDJobStatus.QUEUED):
                return False
            job.status = CFDJobStatus.CANCELLED
            future = self._futures.pop(job_id, None)
            if future:
                future.cancel()
            return True

    def list_jobs(self, status_filter: Optional[CFDJobStatus] = None) -> List[CFDJob]:
        """列出所有任务，可选按状态过滤"""
        with self._lock:
            jobs = list(self._jobs.values())
        if status_filter:
            jobs = [j for j in jobs if j.status == status_filter]
        return jobs

    def get_stats(self) -> Dict:
        """获取 Worker 统计信息"""
        with self._lock:
            counts = {s.value: 0 for s in CFDJobStatus}
            for job in self._jobs.values():
                counts[job.status.value] += 1

            if self._jobs:
                avg_exec = 0.0
                completed = [j for j in self._jobs.values()
                             if j.status == CFDJobStatus.COMPLETED
                             and j.completed_at and j.started_at]
                if completed:
                    avg_exec = sum(j.completed_at - j.started_at for j in completed) / len(completed)

            return {
                "pool_size": self.pool_size,
                "use_processes": self.use_processes,
                "is_running": self._running,
                "total_jobs": len(self._jobs),
                "status_counts": counts,
                "avg_execution_ms": round(avg_exec * 1000, 1) if completed else None,
                "supported_job_types": self.VALID_JOB_TYPES,
            }

    # ------------------------------
    # 监控循环
    # ------------------------------

    def _monitor_loop(self) -> None:
        """后台监控线程，定期清理过期任务"""
        while self._running:
            try:
                with self._lock:
                    now = time.time()
                    expired = [
                        jid for jid, j in self._jobs.items()
                        if j.status in (CFDJobStatus.COMPLETED, CFDJobStatus.FAILED, CFDJobStatus.CANCELLED)
                        and j.completed_at
                        and now - j.completed_at > 300  # 5 分钟后清理
                    ]
                    for jid in expired:
                        del self._jobs[jid]
            except Exception as e:
                logger.error("[CFDWorker] 监控循环异常: %s", e)

            time.sleep(5.0)

    # ------------------------------
    # Context Manager 支持
    # ------------------------------

    def __enter__(self) -> "CFDWorker":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop(wait=True)

    def __del__(self):
        if self._running:
            try:
                self.stop(wait=False)
            except Exception:
                pass
