import math
import time
import pytest
from backend.modules.shape_comparator import (
    ShapeComparator,
    ShapeComparisonRequest,
    ShapeComparisonResult,
)
from backend.modules.era_comparator import (
    EraComparator,
    EraComparisonRequest,
    EraComparisonResult,
)
from backend.modules.field_superposer import (
    FieldSuperposer,
    SuperpositionRequest,
    SuperpositionResult,
)
from backend.modules.vr_whistling_arrow import (
    VRWhistlingArrow,
    LaunchExperienceRequest,
    LaunchExperienceResult,
)
from backend.modules.cfd_worker import (
    CFDWorker,
    CFDJob,
    CFDJobStatus,
)
from backend.physics.volley_simulation import VolleyArrowConfig


# ============================================================
# 1. ShapeComparator 模块测试
# ============================================================

class TestShapeComparator:

    def setup_method(self):
        self.comparator = ShapeComparator()

    def test_instantiation(self):
        assert isinstance(self.comparator, ShapeComparator)
        assert len(self.comparator.available_shapes) >= 4
        assert "conical" in self.comparator.available_shapes

    def test_compare_all_shapes_default(self):
        result = self.comparator.compare(velocity=65.0)
        assert isinstance(result, ShapeComparisonResult)
        assert result.velocity == 65.0
        assert len(result.results) >= 4
        assert "conical" in result.results
        assert "spherical" in result.results

    def test_compare_specific_shapes(self):
        shapes = ["conical", "ogival"]
        result = self.comparator.compare(velocity=65.0, shapes=shapes)
        assert len(result.results) == 2
        assert "blunt" not in result.results
        assert "spherical" not in result.results

    def test_compare_invalid_shape_skipped(self):
        shapes = ["conical", "invalid_shape"]
        result = self.comparator.compare(velocity=65.0, shapes=shapes)
        assert len(result.results) == 1
        assert "conical" in result.results

    def test_compare_no_valid_shapes_raises(self):
        with pytest.raises(ValueError):
            self.comparator.compare(velocity=65.0, shapes=["invalid1", "invalid2"])

    def test_result_contains_aerodynamic_params(self):
        result = self.comparator.compare(velocity=65.0, shapes=["conical"])
        r = result.results["conical"]
        assert "drag_coefficient" in r
        assert "lift_coefficient" in r
        assert "drag_force" in r
        assert "lift_force" in r
        assert "reynolds_number" in r
        assert "mach_number" in r

    def test_ranking_structure(self):
        result = self.comparator.compare(velocity=65.0)
        assert "overall" in result.ranking
        assert "drag_coefficient" in result.ranking
        for metric, ranks in result.ranking.items():
            for shape, rank in ranks.items():
                assert isinstance(rank, (int, float))
                assert rank >= 1

    def test_drag_ranking_ordering(self):
        result = self.comparator.compare(velocity=65.0)
        drag_ranking = result.ranking["drag_coefficient"]
        assert drag_ranking["ogival"] <= drag_ranking["conical"]
        assert drag_ranking["conical"] <= drag_ranking["blunt"]

    def test_velocity_affects_drag_force(self):
        r1 = self.comparator.compare(velocity=40.0, shapes=["conical"])
        r2 = self.comparator.compare(velocity=80.0, shapes=["conical"])
        f1 = r1.results["conical"]["drag_force"]
        f2 = r2.results["conical"]["drag_force"]
        assert f2 > f1, "高速下阻力应更大"

    def test_data_quality_included(self):
        result = self.comparator.compare(velocity=65.0, include_data_quality=True)
        assert len(result.data_quality_summary) >= 4
        for shape, quality in result.data_quality_summary.items():
            assert "worst_provenance" in quality
            assert "fallback_params" in quality

    def test_data_quality_excluded(self):
        result = self.comparator.compare(velocity=65.0, include_data_quality=False)
        assert len(result.data_quality_summary) == 0

    def test_get_shape_profiles(self):
        profiles = self.comparator.get_shape_profiles()
        assert "shapes" in profiles
        assert "profiles" in profiles
        assert "data_quality" in profiles
        assert "provenance_scale" in profiles
        assert len(profiles["shapes"]) >= 4

    def test_get_shape_data_quality_single(self):
        quality = self.comparator.get_shape_data_quality("conical")
        assert "is_experimentally_validated" in quality
        assert "worst_provenance" in quality
        assert "fallback_params" in quality

    def test_to_dict_method(self):
        result = self.comparator.compare(velocity=65.0)
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "velocity" in d
        assert "comparison" in d
        assert "ranking" in d
        assert "data_quality" in d

    def test_aoa_increases_drag(self):
        r0 = self.comparator.compare(velocity=65.0, shapes=["conical"], angle_of_attack=0.0)
        r1 = self.comparator.compare(velocity=65.0, shapes=["conical"], angle_of_attack=0.3)
        cd0 = r0.results["conical"]["drag_coefficient"]
        cd1 = r1.results["conical"]["drag_coefficient"]
        assert cd1 > cd0, "攻角增大时阻力系数应增大"

    def test_custom_fluid_params(self):
        comparator = ShapeComparator(rho=1.0, mu=1.5e-5, c0=340.0)
        result = comparator.compare(velocity=65.0, shapes=["conical"])
        assert result.results["conical"]["reynolds_number"] > 0


# ============================================================
# 2. EraComparator 模块测试
# ============================================================

class TestEraComparator:

    def setup_method(self):
        self.comparator = EraComparator()

    def test_instantiation(self):
        assert isinstance(self.comparator, EraComparator)
        assert self.comparator.ERA_GAP_YEARS == 2200

    def test_compare_default_params(self):
        result = self.comparator.compare(velocity=65.0)
        assert isinstance(result, EraComparisonResult)
        assert result.velocity == 65.0
        assert "mingdi" in result.to_dict()
        assert "modern_whistle" in result.to_dict()

    def test_mingdi_has_frequency(self):
        result = self.comparator.compare(velocity=65.0)
        assert result.mingdi["whistle_frequency"] > 0
        assert result.mingdi["sound_pressure_level"] > 0

    def test_modern_whistle_has_frequency(self):
        result = self.comparator.compare(velocity=65.0)
        assert result.modern_whistle["whistle_frequency"] > 0
        assert result.modern_whistle["sound_pressure_level"] > 0

    def test_comparison_metrics(self):
        result = self.comparator.compare(velocity=65.0)
        comp = result.comparison
        assert "frequency_ratio_mingdi_to_modern" in comp
        assert "spl_difference_db" in comp
        assert "propagation_distance_ratio" in comp
        assert "era_gap_years" in comp
        assert "key_insight" in comp
        assert comp["era_gap_years"] == 2200

    def test_different_models(self):
        result1 = self.comparator.compare(65.0, modern_model="fox40_classic")
        result2 = self.comparator.compare(65.0, modern_model="fox40_mini")
        f1 = result1.modern_whistle["whistle_frequency"]
        f2 = result2.modern_whistle["whistle_frequency"]
        assert f1 != f2

    def test_velocity_affects_mingdi_frequency(self):
        r1 = self.comparator.compare(velocity=40.0)
        r2 = self.comparator.compare(velocity=80.0)
        assert r2.mingdi["whistle_frequency"] > r1.mingdi["whistle_frequency"]
        assert r2.mingdi["sound_pressure_level"] > r1.mingdi["sound_pressure_level"]

    def test_distance_only_affects_spl_not_freq(self):
        r_1m = self.comparator.compare(65.0, distance=1.0)
        r_10m = self.comparator.compare(65.0, distance=10.0)
        assert r_1m.mingdi["whistle_frequency"] == r_10m.mingdi["whistle_frequency"]
        assert r_1m.mingdi["sound_pressure_level"] > r_10m.mingdi["sound_pressure_level"]

    def test_mingdi_shape_affects_result(self):
        r1 = self.comparator.compare(65.0, mingdi_shape="conical")
        r2 = self.comparator.compare(65.0, mingdi_shape="blunt")
        assert r1.mingdi["whistle_frequency"] != r2.mingdi["whistle_frequency"]

    def test_standardization_note_present(self):
        result = self.comparator.compare(65.0)
        assert len(result.standardization_note) > 10
        assert "FOX 40" in result.standardization_note or "满城汉墓" in result.standardization_note

    def test_list_available_models(self):
        models = self.comparator.list_available_models()
        assert "default_model" in models
        assert "models" in models
        assert "fox40_classic" in [m["id"] for m in models["models"]]

    def test_get_model_defaults(self):
        defaults = self.comparator.get_model_defaults("fox40_classic")
        assert defaults is not None
        assert "model_name" in defaults
        assert "dimensions" in defaults

    def test_harmonic_structure(self):
        result = self.comparator.compare(65.0)
        assert len(result.mingdi["harmonic_frequencies"]) == 5
        assert len(result.modern_whistle["harmonic_frequencies"]) >= 4

    def test_mechanisms_different(self):
        result = self.comparator.compare(65.0)
        assert result.mingdi["mechanism"] != result.modern_whistle["mechanism"]

    def test_key_insight_varies_with_velocity(self):
        insights = set()
        for v in [30, 65, 150]:
            r = self.comparator.compare(float(v))
            insights.add(r.comparison["key_insight"])
        assert len(insights) >= 1

    def test_to_dict_method(self):
        result = self.comparator.compare(65.0)
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "mingdi" in d
        assert "modern_whistle" in d
        assert "comparison" in d
        assert "standardization_note" in d


# ============================================================
# 3. FieldSuperposer 模块测试
# ============================================================

class TestFieldSuperposer:

    def setup_method(self):
        self.superposer = FieldSuperposer(backend="numpy")

    def test_instantiation(self):
        assert isinstance(self.superposer, FieldSuperposer)

    def test_available_patterns(self):
        patterns = self.superposer.get_available_patterns()
        assert isinstance(patterns, list)
        assert len(patterns) >= 8
        assert "line" in patterns
        assert "wedge" in patterns
        assert "marching_10" in patterns

    def test_backend_info(self):
        info = self.superposer.get_backend_info()
        assert "current_backend" in info
        assert info["current_backend"] == "numpy"
        assert "supported_backends" in info

    def test_single_arrow_superposition(self):
        arrows = [VolleyArrowConfig(
            id=1, x=0.0, y=0.0, z=1.5,
            velocity=65.0, rotation_speed=100.0,
            spl_1m=85.0, frequency=1500.0,
            shape_profile="conical",
        )]
        result = self.superposer.superpose(
            arrows=arrows,
            grid_size=10,
            grid_extent=20.0,
            binaural=False,
        )
        assert isinstance(result, SuperpositionResult)
        assert result.arrow_count == 1
        assert result.grid_size == 10
        assert len(result.spl_grid) == 10
        assert len(result.spl_grid[0]) == 10
        assert result.centroid_db > 0
        assert result.total_acoustic_power_w > 0

    def test_multiple_arrows_superposition(self):
        arrows = [
            VolleyArrowConfig(id=0, x=-5.0, y=0.0, z=1.5, velocity=65,
                              rotation_speed=100, spl_1m=85, frequency=1500),
            VolleyArrowConfig(id=1, x=5.0, y=0.0, z=1.5, velocity=65,
                              rotation_speed=100, spl_1m=85, frequency=1500),
        ]
        result = self.superposer.superpose(
            arrows=arrows,
            grid_size=20,
            grid_extent=40.0,
            binaural=False,
        )
        assert result.arrow_count == 2
        assert len(result.arrow_sources) == 2
        assert len(result.interference_regions) >= 1

    def test_superposition_enhancement(self):
        arrow_single = VolleyArrowConfig(
            id=0, x=0.0, y=0.0, z=1.5, velocity=65,
            rotation_speed=100, spl_1m=85, frequency=1500
        )
        r_single = self.superposer.superpose([arrow_single], grid_size=10, grid_extent=20.0, binaural=False)

        arrows_dual = [
            VolleyArrowConfig(id=0, x=0.0, y=0.0, z=1.5, velocity=65,
                              rotation_speed=100, spl_1m=85, frequency=1500),
            VolleyArrowConfig(id=1, x=0.01, y=0.01, z=1.5, velocity=65,
                              rotation_speed=100, spl_1m=85, frequency=1500),
        ]
        r_dual = self.superposer.superpose(arrows_dual, grid_size=10, grid_extent=20.0, binaural=False)
        theoretical = 10 * math.log10(2)
        actual = r_dual.centroid_db - r_single.centroid_db
        assert abs(actual - theoretical) < 3.0

    def test_create_preset_line(self):
        arrows = self.superposer.create_preset_arrows(
            pattern="line", count=5, velocity=65.0, spacing=5.0
        )
        assert len(arrows) == 5
        x_coords = sorted([a.x for a in arrows])
        for i in range(4):
            assert abs(x_coords[i + 1] - x_coords[i] - 5.0) < 0.01

    def test_create_preset_marching_10(self):
        arrows = self.superposer.create_preset_arrows(pattern="marching_10", velocity=65.0)
        assert len(arrows) == 10

    def test_create_preset_ambush_20(self):
        arrows = self.superposer.create_preset_arrows(pattern="ambush_20", velocity=65.0)
        assert len(arrows) == 20

    def test_create_preset_single(self):
        arrows = self.superposer.create_preset_arrows(pattern="single", velocity=65.0)
        assert len(arrows) == 1

    def test_binaural_audio_in_result(self):
        arrows = [VolleyArrowConfig(
            id=1, x=10.0, y=5.0, z=1.5, velocity=65,
            rotation_speed=100, spl_1m=85, frequency=1500
        )]
        result = self.superposer.superpose(
            arrows=arrows,
            grid_size=10,
            grid_extent=30.0,
            listener_position=(0.0, 0.0, 1.5),
            binaural=True,
        )
        assert result.audio_synthesis is not None
        assert "binaural" in result.audio_synthesis
        assert result.audio_synthesis["binaural"]["enabled"] is True

    def test_interference_regions_structure(self):
        arrows = [
            VolleyArrowConfig(id=0, x=-10, y=0, z=1.5, velocity=65,
                              rotation_speed=100, spl_1m=90, frequency=1500),
            VolleyArrowConfig(id=1, x=10, y=0, z=1.5, velocity=65,
                              rotation_speed=100, spl_1m=90, frequency=1500),
        ]
        result = self.superposer.superpose(arrows, grid_size=30, grid_extent=60.0, binaural=False)
        for reg in result.interference_regions:
            assert "type" in reg
            assert reg["type"] in ("constructive", "destructive", "constructive_destructive_alternating")
            assert "grid_ratio" in reg
            assert 0 <= reg["grid_ratio"] <= 1
            assert "threshold_db" in reg

    def test_computation_time_recorded(self):
        arrows = [VolleyArrowConfig(
            id=1, x=0, y=0, z=1.5, velocity=65,
            rotation_speed=100, spl_1m=85, frequency=1500
        )]
        result = self.superposer.superpose(arrows, grid_size=20, grid_extent=30.0, binaural=False)
        assert result.computation_ms >= 0

    def test_estimate_computation_time(self):
        t = self.superposer.estimate_computation_time(arrow_count=20, grid_size=40)
        assert t > 0

    def test_to_dict_method(self):
        arrows = [VolleyArrowConfig(
            id=1, x=0, y=0, z=1.5, velocity=65,
            rotation_speed=100, spl_1m=85, frequency=1500
        )]
        result = self.superposer.superpose(arrows, grid_size=10, grid_extent=20.0, binaural=False)
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "arrow_count" in d
        assert "spl_grid" in d
        assert "interference_regions" in d
        assert "centroid_db" in d


# ============================================================
# 4. VRWhistlingArrow 模块测试
# ============================================================

class TestVRWhistlingArrow:

    def setup_method(self):
        self.vr = VRWhistlingArrow()

    def test_instantiation(self):
        assert isinstance(self.vr, VRWhistlingArrow)

    def test_waveform_by_shape(self):
        assert self.vr.WAVEFORM_BY_SHAPE["conical"] == "sawtooth"
        assert self.vr.WAVEFORM_BY_SHAPE["spherical"] == "square"
        assert self.vr.WAVEFORM_BY_SHAPE["blunt"] == "triangle"
        assert self.vr.WAVEFORM_BY_SHAPE["ogival"] == "sine"

    def test_launch_basic(self):
        result = self.vr.launch(
            velocity=65.0,
            launch_angle=0.4,
            shape_profile="conical",
            observer_distance=30.0,
        )
        assert isinstance(result, LaunchExperienceResult)
        assert result.audio is not None
        assert result.trajectory_summary is not None
        assert result.aerodynamics is not None
        assert result.acoustics is not None

    def test_trajectory_summary_fields(self):
        result = self.vr.launch(65.0, 0.4, shape_profile="conical", observer_distance=30.0)
        traj = result.trajectory_summary
        assert "peak_altitude" in traj
        assert "estimated_range" in traj
        assert "flight_time" in traj
        assert traj["peak_altitude"] > 0
        assert traj["estimated_range"] > 0
        assert traj["flight_time"] > 0

    def test_audio_has_frequency(self):
        result = self.vr.launch(65.0, 0.4, shape_profile="conical", observer_distance=30.0)
        audio = result.audio
        assert "dominant_frequency" in audio
        assert audio["dominant_frequency"] > 0
        assert "harmonic_structure" in audio
        assert len(audio["harmonic_structure"]) >= 4

    def test_audio_has_adsr(self):
        result = self.vr.launch(65.0, 0.4, shape_profile="conical", observer_distance=30.0)
        adsr = result.audio["adsr_envelope"]
        assert adsr["attack_sec"] > 0
        assert adsr["decay_sec"] > 0
        assert adsr["release_sec"] > 0

    def test_binaural_in_audio(self):
        result = self.vr.launch(65.0, 0.4, shape_profile="conical", observer_distance=30.0)
        assert "binaural" in result.audio
        assert result.audio["binaural"]["enabled"] is True
        bn = result.audio["binaural"]
        assert "itd_parameters" in bn
        assert "ild_parameters" in bn
        assert "hrtf_gains_db" in bn

    def test_different_shapes_different_waveforms(self):
        shapes = ["conical", "spherical", "blunt", "ogival"]
        results = {}
        for shape in shapes:
            results[shape] = self.vr.launch(
                65.0, 0.4, shape_profile=shape, observer_distance=30.0
            )
        waveforms = [r.audio["waveform_type"] for r in results.values()]
        assert len(set(waveforms)) >= 2

    def test_different_shapes_different_timbres(self):
        shapes = ["conical", "spherical", "blunt", "ogival"]
        timbres = []
        for shape in shapes:
            r = self.vr.launch(65.0, 0.4, shape_profile=shape, observer_distance=30.0)
            timbres.append(r.audio["timbre"])
        assert len(set(timbres)) >= 2

    def test_launch_angle_affects_range(self):
        r_low = self.vr.launch(65.0, 0.1, shape_profile="conical", observer_distance=30.0)
        r_high = self.vr.launch(65.0, 0.7, shape_profile="conical", observer_distance=30.0)
        assert r_high.trajectory_summary["peak_altitude"] > r_low.trajectory_summary["peak_altitude"]

    def test_velocity_affects_range(self):
        r_slow = self.vr.launch(40.0, 0.4, shape_profile="conical", observer_distance=30.0)
        r_fast = self.vr.launch(80.0, 0.4, shape_profile="conical", observer_distance=30.0)
        assert r_fast.trajectory_summary["estimated_range"] > r_slow.trajectory_summary["estimated_range"]

    def test_estimate_trajectory(self):
        traj = self.vr.estimate_trajectory(65.0, 0.4)
        assert "peak_altitude" in traj
        assert "estimated_range" in traj
        assert "flight_time" in traj
        assert "trajectory_points" in traj
        assert len(traj["trajectory_points"]) > 0

    def test_get_available_shapes(self):
        shapes = self.vr.get_available_shapes()
        assert isinstance(shapes, list)
        assert len(shapes) >= 4
        assert "conical" in shapes
        assert "ogival" in shapes

    def test_get_shape_timbres(self):
        timbres = self.vr.get_shape_timbres()
        assert isinstance(timbres, dict)
        assert len(timbres) >= 4
        for shape, timbre in timbres.items():
            assert isinstance(timbre, str)
            assert len(timbre) > 0

    def test_observer_distance_affects_spl(self):
        r_near = self.vr.launch(65.0, 0.4, shape_profile="conical", observer_distance=10.0)
        r_far = self.vr.launch(65.0, 0.4, shape_profile="conical", observer_distance=100.0)
        assert r_near.acoustics["sound_pressure_level"] > r_far.acoustics["sound_pressure_level"]

    def test_observer_heading_affects_binaural(self):
        r0 = self.vr.launch(65.0, 0.4, shape_profile="conical",
                            observer_distance=30.0, observer_heading_deg=0.0)
        r90 = self.vr.launch(65.0, 0.4, shape_profile="conical",
                             observer_distance=30.0, observer_heading_deg=90.0)
        itd0 = r0.audio["binaural"]["itd_parameters"]["interaural_time_diff_us"]
        ild0 = r0.audio["binaural"]["ild_parameters"]["interaural_level_diff_db"]
        itd90 = r90.audio["binaural"]["itd_parameters"]["interaural_time_diff_us"]
        ild90 = r90.audio["binaural"]["ild_parameters"]["interaural_level_diff_db"]
        assert (itd0 != itd90) or (ild0 != ild90)

    def test_include_aerodynamics_false(self):
        result = self.vr.launch(
            65.0, 0.4, shape_profile="conical", observer_distance=30.0,
            include_aerodynamics=False, include_acoustics=False
        )
        assert result.aerodynamics is None
        assert result.acoustics is None

    def test_duration_sec_param(self):
        result = self.vr.launch(
            65.0, 0.4, shape_profile="conical", observer_distance=30.0, duration_sec=5.0
        )
        assert result.audio["total_duration_sec"] == 5.0

    def test_to_dict_method(self):
        result = self.vr.launch(65.0, 0.4, shape_profile="conical", observer_distance=30.0)
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "audio" in d
        assert "trajectory_summary" in d
        assert "aerodynamics" in d
        assert "acoustics" in d

    def test_source_position_calculation(self):
        pos = self.vr._calculate_source_position(10.0, 0.0, 50.0)
        assert len(pos) == 3
        assert abs(pos[0] - 10.0) < 0.01
        assert abs(pos[1] - 0.0) < 0.01
        assert pos[2] > 0

    def test_source_position_with_heading(self):
        pos = self.vr._calculate_source_position(10.0, 90.0, 50.0)
        assert abs(pos[0] - 10.0) < 0.01
        assert abs(pos[1]) < 0.01
        assert pos[2] > 0


# ============================================================
# 5. CFDWorker 模块测试
# ============================================================

class TestCFDWorker:

    def test_instantiation(self):
        worker = CFDWorker(pool_size=1, use_processes=False)
        assert isinstance(worker, CFDWorker)
        assert worker.pool_size == 1
        assert worker.use_processes is False
        assert worker._running is False

    def test_valid_job_types(self):
        assert len(CFDWorker.VALID_JOB_TYPES) >= 4
        assert "sst_komega_turbulence" in CFDWorker.VALID_JOB_TYPES
        assert "trajectory_simulation" in CFDWorker.VALID_JOB_TYPES

    def test_invalid_job_type_raises(self):
        worker = CFDWorker(pool_size=1, use_processes=False)
        with pytest.raises(ValueError):
            worker.submit_job("invalid_job_type", {"velocity": 65.0})

    def test_start_stop_threading_mode(self):
        worker = CFDWorker(pool_size=1, use_processes=False)
        assert worker._running is False
        worker.start()
        assert worker._running is True
        worker.stop(wait=True)
        assert worker._running is False

    def test_submit_job_threading_mode(self):
        worker = CFDWorker(pool_size=1, use_processes=False)
        worker.start()
        try:
            job_id = worker.submit_job(
                job_type="full_aerodynamics",
                params={"velocity": 65.0},
                priority=5,
            )
            assert isinstance(job_id, str)
            assert job_id.startswith("cfd-")

            time.sleep(0.2)

            job = worker.get_job_result(job_id, timeout=2.0)
            assert job is not None
            assert job.status == CFDJobStatus.COMPLETED
            assert job.result is not None
            assert "drag_coefficient" in job.result
        finally:
            worker.stop(wait=True)

    def test_sst_komega_job(self):
        worker = CFDWorker(pool_size=1, use_processes=False)
        worker.start()
        try:
            job_id = worker.submit_job(
                job_type="sst_komega_turbulence",
                params={"velocity": 65.0, "turbulence_intensity": 0.05},
            )
            time.sleep(0.3)
            job = worker.get_job_result(job_id, timeout=3.0)
            assert job is not None
            assert job.status == CFDJobStatus.COMPLETED
            assert "k" in job.result
            assert "omega" in job.result
            assert "reynolds_number" in job.result
        finally:
            worker.stop(wait=True)

    def test_trajectory_simulation_job(self):
        worker = CFDWorker(pool_size=1, use_processes=False)
        worker.start()
        try:
            job_id = worker.submit_job(
                job_type="trajectory_simulation",
                params={"velocity": 65.0, "launch_angle": 0.3},
            )
            time.sleep(0.3)
            job = worker.get_job_result(job_id, timeout=3.0)
            assert job is not None
            assert job.status == CFDJobStatus.COMPLETED
            assert "trajectory_points" in job.result
            assert "peak_altitude" in job.result
            assert "final_range" in job.result
        finally:
            worker.stop(wait=True)

    def test_boundary_layer_job(self):
        worker = CFDWorker(pool_size=1, use_processes=False)
        worker.start()
        try:
            job_id = worker.submit_job(
                job_type="boundary_layer_profile",
                params={"velocity": 65.0, "num_points": 20},
            )
            time.sleep(0.3)
            job = worker.get_job_result(job_id, timeout=3.0)
            assert job is not None
            assert job.status == CFDJobStatus.COMPLETED
            assert "boundary_layer_thickness_m" in job.result
            assert "profile_type" in job.result
            assert len(job.result["u_over_U"]) == 20
        finally:
            worker.stop(wait=True)

    def test_shock_wave_analysis_subsonic(self):
        worker = CFDWorker(pool_size=1, use_processes=False)
        worker.start()
        try:
            job_id = worker.submit_job(
                job_type="shock_wave_analysis",
                params={"velocity": 50.0},
            )
            time.sleep(0.2)
            job = worker.get_job_result(job_id, timeout=2.0)
            assert job is not None
            assert job.result["flow_regime"] == "subsonic"
            assert job.result["has_shock"] is False
        finally:
            worker.stop(wait=True)

    def test_shock_wave_analysis_supersonic(self):
        worker = CFDWorker(pool_size=1, use_processes=False)
        worker.start()
        try:
            job_id = worker.submit_job(
                job_type="shock_wave_analysis",
                params={"velocity": 500.0},
            )
            time.sleep(0.2)
            job = worker.get_job_result(job_id, timeout=2.0)
            assert job is not None
            assert job.result["flow_regime"] in ("transonic", "supersonic")
            assert job.result["has_shock"] is True
            assert "mach_angle_deg" in job.result
        finally:
            worker.stop(wait=True)

    def test_job_status_tracking(self):
        worker = CFDWorker(pool_size=1, use_processes=False)
        worker.start()
        try:
            job_id = worker.submit_job(
                "full_aerodynamics", {"velocity": 65.0}
            )
            status = worker.get_job_status(job_id)
            assert status is not None
            assert status.job_id == job_id
            assert status.job_type == "full_aerodynamics"
        finally:
            worker.stop(wait=True)

    def test_list_jobs(self):
        worker = CFDWorker(pool_size=1, use_processes=False)
        worker.start()
        try:
            job_id = worker.submit_job(
                "full_aerodynamics", {"velocity": 65.0}
            )
            time.sleep(0.2)
            jobs = worker.list_jobs()
            assert len(jobs) >= 1
            assert any(j.job_id == job_id for j in jobs)

            completed = worker.list_jobs(status_filter=CFDJobStatus.COMPLETED)
            assert len(completed) >= 1
        finally:
            worker.stop(wait=True)

    def test_get_stats(self):
        worker = CFDWorker(pool_size=1, use_processes=False)
        worker.start()
        try:
            worker.submit_job("full_aerodynamics", {"velocity": 65.0})
            time.sleep(0.2)
            stats = worker.get_stats()
            assert "pool_size" in stats
            assert "total_jobs" in stats
            assert "status_counts" in stats
            assert stats["pool_size"] == 1
            assert stats["total_jobs"] >= 1
        finally:
            worker.stop(wait=True)

    def test_cancel_pending_job(self):
        worker = CFDWorker(pool_size=1, use_processes=False)
        worker.start()
        try:
            job_id = worker.submit_job(
                "full_aerodynamics", {"velocity": 65.0}, priority=10
            )
            with worker._lock:
                worker._jobs[job_id].status = CFDJobStatus.QUEUED
            success = worker.cancel_job(job_id)
            assert success is True
            job = worker.get_job_status(job_id)
            assert job.status == CFDJobStatus.CANCELLED
        finally:
            worker.stop(wait=True)

    def test_cancel_running_job_fails(self):
        worker = CFDWorker(pool_size=1, use_processes=False)
        worker.start()
        try:
            job_id = worker.submit_job(
                "full_aerodynamics", {"velocity": 65.0}
            )
            with worker._lock:
                worker._jobs[job_id].status = CFDJobStatus.RUNNING
            success = worker.cancel_job(job_id)
            assert success is False
        finally:
            worker.stop(wait=True)

    def test_job_to_dict(self):
        job = CFDJob(
            job_id="test-123",
            job_type="full_aerodynamics",
            params={"velocity": 65.0},
            status=CFDJobStatus.COMPLETED,
            result={"drag_coefficient": 0.5},
            priority=5,
        )
        job.started_at = time.time() - 0.1
        job.completed_at = time.time()
        d = job.to_dict()
        assert d["job_id"] == "test-123"
        assert d["status"] == "completed"
        assert "execution_ms" in d
        assert "result_summary" in d

    def test_priority_support(self):
        worker = CFDWorker(pool_size=1, use_processes=False)
        worker.start()
        try:
            job_id = worker.submit_job(
                "full_aerodynamics", {"velocity": 65.0}, priority=8
            )
            time.sleep(0.2)
            job = worker.get_job_status(job_id)
            assert job.priority == 8
        finally:
            worker.stop(wait=True)

    def test_nonexistent_job_returns_none(self):
        worker = CFDWorker(pool_size=1, use_processes=False)
        worker.start()
        try:
            job = worker.get_job_result("nonexistent-job-id")
            assert job is None
        finally:
            worker.stop(wait=True)

    def test_context_manager(self):
        with CFDWorker(pool_size=1, use_processes=False) as worker:
            assert worker._running is True
            job_id = worker.submit_job(
                "full_aerodynamics", {"velocity": 65.0}
            )
            time.sleep(0.2)
            job = worker.get_job_result(job_id, timeout=2.0)
            assert job is not None
            assert job.status == CFDJobStatus.COMPLETED

    def test_job_callback(self):
        callback_called = []

        def callback(job):
            callback_called.append(job.job_id)

        worker = CFDWorker(pool_size=1, use_processes=False)
        worker.start()
        try:
            job_id = worker.submit_job(
                "full_aerodynamics", {"velocity": 65.0}, callback=callback
            )
            time.sleep(0.3)
            assert job_id in callback_called
        finally:
            worker.stop(wait=True)
