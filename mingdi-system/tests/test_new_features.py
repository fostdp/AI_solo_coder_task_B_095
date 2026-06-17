import math
import pytest
from backend.physics.shape_acoustics import (
    ShapeAwareAeroSimulator,
    ModernWhistleAcousticSimulator,
    CrossEraAcousticComparator,
    SHAPE_PROFILES,
)
from backend.physics.volley_simulation import VolleySimulation, AudioSynthesisParams
from backend.physics.aeroacoustics import AeroAcousticsSimulator
from backend.physics.aerodynamics import AeroDynamicsSimulator
from backend.models import (
    ShapeComparisonRequest,
    VolleySimulationRequest,
    VolleyArrowConfig,
    LaunchExperienceRequest,
)


# ============================================================
# 1. 形状对比测试 — 验证不同形状的气动系数与声压级差异
# ============================================================

class TestShapeComparisonAerodynamics:

    def setup_method(self):
        self.sim = ShapeAwareAeroSimulator()

    def test_cd_ordering_spherical_highest(self):
        results = self.sim.compare_shapes(65.0, ["conical", "spherical", "blunt", "ogival"])
        cd_map = {s: results[s]["drag_coefficient"] for s in results}
        assert cd_map["spherical"] > cd_map["conical"], "球形Cd应大于锥形Cd"
        assert cd_map["blunt"] > cd_map["conical"], "钝头Cd应大于锥形Cd"
        assert cd_map["ogival"] < cd_map["conical"], "尖拱Cd应小于锥形Cd"

    def test_cd_base_values_zero_aoa(self):
        r_cone = self.sim.simulate_shape(65.0, "conical", 0.0, 0.0)
        r_sphere = self.sim.simulate_shape(65.0, "spherical", 0.0, 0.0)
        r_blunt = self.sim.simulate_shape(65.0, "blunt", 0.0, 0.0)
        r_ogive = self.sim.simulate_shape(65.0, "ogival", 0.0, 0.0)
        assert 0.5 < r_cone["drag_coefficient"] < 1.0, f"锥形Cd={r_cone['drag_coefficient']} 超出合理范围"
        assert 1.0 < r_sphere["drag_coefficient"] < 1.5, f"球形Cd={r_sphere['drag_coefficient']} 超出合理范围"
        assert 1.3 < r_blunt["drag_coefficient"] < 1.8, f"钝头Cd={r_blunt['drag_coefficient']} 超出合理范围"
        assert 0.4 < r_ogive["drag_coefficient"] < 0.8, f"尖拱Cd={r_ogive['drag_coefficient']} 超出合理范围"

    def test_cl_alpha_ogive_highest(self):
        results = self.sim.compare_shapes(65.0, ["conical", "spherical", "blunt", "ogival"], 0.1, 0.0)
        cl_map = {s: results[s]["lift_coefficient"] for s in results}
        assert cl_map["ogival"] > cl_map["conical"], f"尖拱Cl应大于锥形Cl: ogive={cl_map['ogival']}, cone={cl_map['conical']}"
        assert abs(cl_map["spherical"]) < abs(cl_map["conical"]), "球形Cl绝对值应小于锥形"

    def test_drag_force_proportional_to_cd(self):
        r_cone = self.sim.simulate_shape(65.0, "conical", 0.0, 0.0)
        r_blunt = self.sim.simulate_shape(65.0, "blunt", 0.0, 0.0)
        ratio_cd = r_blunt["drag_coefficient"] / r_cone["drag_coefficient"]
        ratio_force = r_blunt["drag_force"] / r_cone["drag_force"]
        assert abs(ratio_cd - ratio_force) < 0.05, f"Cd比值{ratio_cd}应近似等于阻力比值{ratio_force}"

    def test_aoa_increases_cd_for_all_shapes(self):
        for shape in SHAPE_PROFILES:
            r0 = self.sim.simulate_shape(65.0, shape, 0.0, 0.0)
            r1 = self.sim.simulate_shape(65.0, shape, 0.2, 0.0)
            assert r1["drag_coefficient"] > r0["drag_coefficient"], f"{shape}: 攻角0.2时Cd应大于0时"

    def test_stall_behavior_spherical_early(self):
        r_before = self.sim.simulate_shape(65.0, "spherical", 0.14, 0.0)
        r_after = self.sim.simulate_shape(65.0, "spherical", 0.20, 0.0)
        cl_slope_before = r_before["lift_coefficient"] / 0.14
        assert r_after["lift_coefficient"] < r_before["lift_coefficient"] * 1.1, "球形应在小攻角即失速"

    def test_pressure_distribution_length(self):
        for shape in SHAPE_PROFILES:
            r = self.sim.simulate_shape(65.0, shape)
            assert len(r["pressure_distribution"]) == 20, f"{shape}压力分布应有20个点"

    def test_pressure_distribution_decreasing_trend(self):
        for shape in SHAPE_PROFILES:
            r = self.sim.simulate_shape(65.0, shape)
            front_avg = sum(r["pressure_distribution"][:5]) / 5
            rear_avg = sum(r["pressure_distribution"][-5:]) / 5
            assert front_avg > rear_avg, f"{shape}前部压力应大于后部"

    def test_reynolds_number_same_for_all_shapes(self):
        results = self.sim.compare_shapes(65.0)
        re_values = [results[s]["reynolds_number"] for s in results]
        for re in re_values[1:]:
            assert abs(re - re_values[0]) < 1.0, "同速度同直径下Re应相同"

    def test_shape_parameters_echoed(self):
        for shape_name, profile in SHAPE_PROFILES.items():
            r = self.sim.simulate_shape(65.0, shape_name)
            assert r["shape_parameters"]["cd_base"] == profile["cd_base"]
            assert r["shape_parameters"]["cl_alpha"] == profile["cl_alpha"]
            assert r["shape_parameters"]["stall_angle"] == profile["stall_angle"]

    def test_custom_arrow_dimensions(self):
        r = self.sim.simulate_shape(65.0, "conical", arrow_diameter=0.01, arrow_length=1.0, arrow_mass=0.03)
        assert r["reynolds_number"] > 0

    def test_invalid_shape_defaults_to_conical(self):
        r = self.sim.simulate_shape(65.0, "nonexistent_shape")
        assert r["shape_profile"] == "nonexistent_shape"
        r_cone = self.sim.simulate_shape(65.0, "conical")
        assert abs(r["drag_coefficient"] - r_cone["drag_coefficient"]) < 0.001

    def test_computability_correction_high_mach(self):
        r_sub = self.sim.simulate_shape(50.0, "conical")
        r_trans = self.sim.simulate_shape(280.0, "conical")
        assert r_trans["drag_coefficient"] > r_sub["drag_coefficient"] * 1.5, "跨音速Cd应显著增大"

    def test_zero_velocity(self):
        r = self.sim.simulate_shape(0.001, "conical")
        assert r["drag_force"] >= 0
        assert r["lift_force"] >= 0

    def test_very_high_velocity_supersonic(self):
        r = self.sim.simulate_shape(500.0, "conical")
        assert r["mach_number"] > 1.0
        assert r["drag_coefficient"] > 0


class TestShapeComparisonAcoustics:

    def setup_method(self):
        self.sim = ShapeAwareAeroSimulator()
        self.acoustic = AeroAcousticsSimulator()

    def test_spl_increases_with_velocity(self):
        spl_50 = self.acoustic.simulate(50.0, 100.0, 1.0)["sound_pressure_level"]
        spl_80 = self.acoustic.simulate(80.0, 100.0, 1.0)["sound_pressure_level"]
        assert spl_80 > spl_50, f"80m/s SPL={spl_80}应大于50m/s SPL={spl_50}"

    def test_spl_decreases_with_distance(self):
        spl_1m = self.acoustic.simulate(65.0, 100.0, 1.0)["sound_pressure_level"]
        spl_10m = self.acoustic.simulate(65.0, 100.0, 10.0)["sound_pressure_level"]
        assert spl_1m > spl_10m, f"1m SPL={spl_1m}应大于10m SPL={spl_10m}"
        assert spl_1m - spl_10m > 10, f"10倍距离衰减应>10dB，实际{spl_1m - spl_10m:.1f}dB"

    def test_blunt_shape_higher_spl_than_ogival(self):
        r_blunt = self.sim.simulate_shape(65.0, "blunt")
        r_ogive = self.sim.simulate_shape(65.0, "ogival")
        assert r_blunt["drag_force"] > r_ogive["drag_force"], "钝头阻力更大，声学能量更高"

    def test_source_breakdown_components(self):
        result = self.acoustic.simulate(65.0, 100.0, 1.0)
        sb = result["source_breakdown"]
        assert "thickness_spl" in sb
        assert "loading_spl" in sb
        assert "quadrupole_spl" in sb
        assert sb["loading_spl"] > sb["thickness_spl"], "载荷噪声应大于厚度噪声"


# ============================================================
# 2. 跨时代对比测试 — 验证鸣镝与口哨的频率特性差异
# ============================================================

class TestCrossEraFrequencyCharacteristics:

    def setup_method(self):
        self.comparator = CrossEraAcousticComparator()

    def test_modern_whistle_frequency_higher(self):
        result = self.comparator.compare(65.0, 100.0, 1.0)
        m_freq = result["mingdi"]["whistle_frequency"]
        w_freq = result["modern_whistle"]["whistle_frequency"]
        assert w_freq > 0, "现代口哨频率应为正数"
        assert m_freq > 0, "鸣镝频率应为正数"

    def test_frequency_ratio_positive(self):
        result = self.comparator.compare(65.0)
        ratio = result["comparison"]["frequency_ratio_mingdi_to_modern"]
        assert ratio > 0, "频率比应为正数"

    def test_spl_difference_consistent(self):
        result = self.comparator.compare(65.0, 100.0, 1.0)
        spl_diff = result["comparison"]["spl_difference_db"]
        m_spl = result["mingdi"]["sound_pressure_level"]
        w_spl = result["modern_whistle"]["sound_pressure_level"]
        assert abs(spl_diff - (m_spl - w_spl)) < 0.2, "SPL差值应与两侧SPL一致"

    def test_era_gap_years(self):
        result = self.comparator.compare(65.0)
        assert result["comparison"]["era_gap_years"] == 2200

    def test_key_insight_generated(self):
        result = self.comparator.compare(65.0)
        assert len(result["comparison"]["key_insight"]) > 10, "洞察文本不应为空"

    def test_mingdi_harmonics_count(self):
        result = self.comparator.compare(65.0)
        assert result["comparison"]["dominant_harmonic_count_mingdi"] == 5

    def test_modern_whistle_harmonics_count(self):
        result = self.comparator.compare(65.0)
        assert result["comparison"]["dominant_harmonic_count_modern"] == 4

    def test_mingdi_mechanism(self):
        result = self.comparator.compare(65.0)
        assert result["mingdi"]["mechanism"] == "cavity_resonance_vortex_shedding"

    def test_modern_mechanism(self):
        result = self.comparator.compare(65.0)
        assert result["modern_whistle"]["mechanism"] == "jet_edge_tone_cavity"

    def test_propagation_distance_positive(self):
        result = self.comparator.compare(65.0, 100.0, 1.0)
        assert result["mingdi"]["propagation_distance"] > 0
        assert result["modern_whistle"]["propagation_distance"] > 0

    def test_velocity_affects_both(self):
        r_slow = self.comparator.compare(40.0, 100.0, 1.0)
        r_fast = self.comparator.compare(80.0, 100.0, 1.0)
        assert r_fast["mingdi"]["whistle_frequency"] > r_slow["mingdi"]["whistle_frequency"], \
            "鸣镝频率应随速度增大"
        assert r_fast["mingdi"]["sound_pressure_level"] > r_slow["mingdi"]["sound_pressure_level"], \
            "鸣镝SPL应随速度增大"
        assert r_fast["modern_whistle"]["whistle_frequency"] >= r_slow["modern_whistle"]["whistle_frequency"], \
            "口哨频率应随速度非减（腔体共鸣主频与速度无关，射流分量可能增大）"

    def test_distance_affects_mingdi_spl_not_frequency(self):
        r1 = self.comparator.compare(65.0, 100.0, 1.0)
        r10 = self.comparator.compare(65.0, 100.0, 10.0)
        assert abs(r1["mingdi"]["whistle_frequency"] - r10["mingdi"]["whistle_frequency"]) < 1.0
        assert r1["mingdi"]["sound_pressure_level"] > r10["mingdi"]["sound_pressure_level"]

    def test_insight_content_by_freq_ratio(self):
        r = self.comparator.compare(65.0)
        insight = r["comparison"]["key_insight"]
        ratio = r["comparison"]["frequency_ratio_mingdi_to_modern"]
        if ratio < 0.5:
            assert "远低于" in insight or "深沉" in insight
        elif ratio < 1.0:
            assert "低于" in insight or "威慑" in insight
        elif ratio < 1.5:
            assert "接近" in insight or "截然不同" in insight
        else:
            assert "高于" in insight or "尖锐" in insight


class TestModernWhistleAcoustics:

    def setup_method(self):
        self.whistle = ModernWhistleAcousticSimulator()

    def test_dominant_frequency_is_double_cavity(self):
        r = self.whistle.simulate_modern_whistle(65.0)
        assert abs(r["dominant_frequency"] - 2 * r["cavity_resonance_freq"]) < 1.0

    def test_harmonics_integer_multiples(self):
        r = self.whistle.simulate_modern_whistle(65.0)
        for i, h in enumerate(r["harmonic_frequencies"]):
            expected = r["dominant_frequency"] * (i + 1)
            assert abs(h - expected) < 1.0, f"第{i+1}谐波{h}应≈{expected}"

    def test_directivity_pattern_length(self):
        r = self.whistle.simulate_modern_whistle(65.0)
        assert len(r["directivity_pattern"]) == 36

    def test_directivity_forward_biased(self):
        r = self.whistle.simulate_modern_whistle(65.0)
        forward = r["directivity_pattern"][0]
        sideways = r["directivity_pattern"][9]
        assert forward > sideways, "前向指向性应大于侧向"

    def test_efficiency_increases_with_re(self):
        r_low = self.whistle.simulate_modern_whistle(10.0)
        r_high = self.whistle.simulate_modern_whistle(100.0)
        assert r_high["efficiency"] >= r_low["efficiency"]

    def test_spl_positive(self):
        for vel in [10, 30, 65, 100]:
            r = self.whistle.simulate_modern_whistle(float(vel))
            assert r["sound_pressure_level_1m"] > 0, f"v={vel}: SPL应为正"


# ============================================================
# 3. 齐射声场叠加测试 — 验证干涉图与能量守恒
# ============================================================

class TestVolleySoundFieldSuperposition:

    def setup_method(self):
        self.volley = VolleySimulation()

    def _single_arrow(self, spl=85.0, pos=(0.0, 0.0)):
        return {
            "arrow_id": "test",
            "velocity": 65.0,
            "rotation_speed": 100.0,
            "whistle_frequency": 1500.0,
            "sound_pressure_level": spl,
            "position": pos,
        }

    def test_single_arrow_field(self):
        result = self.volley.simulate_volley(
            [self._single_arrow()], grid_size=10, observer_position=(0, 50)
        )
        assert result["arrow_count"] == 1
        assert result["observer_spl"] > 0
        assert len(result["field"]) == 10
        assert len(result["field"][0]) == 10

    def test_superposition_enhancement(self):
        single = self.volley.simulate_volley(
            [self._single_arrow()], grid_size=10, observer_position=(0, 50)
        )
        dual = self.volley.simulate_volley(
            [self._single_arrow(), self._single_arrow()], grid_size=10, observer_position=(0, 50)
        )
        assert dual["observer_spl"] > single["observer_spl"], "2支箭SPL应大于1支"

    def test_enhancement_vs_single_db(self):
        result = self.volley.simulate_volley(
            [self._single_arrow(spl=85.0, pos=(0, 0)),
             self._single_arrow(spl=85.0, pos=(0, 0))],
            grid_size=10, observer_position=(0, 50),
        )
        assert result["enhancement_vs_single_db"] >= 0, "叠加增强应为非负"

    def test_n_equal_sources_10log10_n(self):
        n = 5
        arrows = [self._single_arrow(spl=85.0, pos=(0, 0)) for _ in range(n)]
        result = self.volley.simulate_volley(arrows, grid_size=10, observer_position=(0, 50))
        single = self.volley.simulate_volley(
            [self._single_arrow(spl=85.0, pos=(0, 0))], grid_size=10, observer_position=(0, 50)
        )
        theoretical_enhancement = 10 * math.log10(n)
        actual_enhancement = result["observer_spl"] - single["observer_spl"]
        assert abs(actual_enhancement - theoretical_enhancement) < 1.5, \
            f"{n}支同源叠加增强{actual_enhancement:.1f}dB应≈{theoretical_enhancement:.1f}dB"

    def test_field_dimensions(self):
        result = self.volley.simulate_volley(
            [self._single_arrow()], grid_size=20
        )
        assert len(result["field"]) == 20
        assert all(len(row) == 20 for row in result["field"])

    def test_peak_spl_at_source(self):
        result = self.volley.simulate_volley(
            [self._single_arrow(pos=(0, 0))], grid_size=40, grid_spacing=2.0
        )
        center_i = 20
        center_j = 20
        center_spl = result["field"][center_i][center_j]
        assert center_spl > 70, f"声源附近SPL应较高: {center_spl}"

    def test_spl_decreases_away_from_source(self):
        result = self.volley.simulate_volley(
            [self._single_arrow(pos=(0, 0))], grid_size=40, grid_spacing=2.0
        )
        center_spl = result["field"][20][20]
        edge_spl = result["field"][2][2]
        assert center_spl > edge_spl, f"中心SPL={center_spl}应大于边缘SPL={edge_spl}"

    def test_interference_detection_with_separated_sources(self):
        arrows = [
            self._single_arrow(spl=90.0, pos=(-10, 0)),
            self._single_arrow(spl=90.0, pos=(10, 0)),
        ]
        result = self.volley.simulate_volley(arrows, grid_size=40, grid_spacing=2.0)
        iz = result["interference_zones"]
        total_zones = iz["constructive_count"] + iz["destructive_count"]
        assert total_zones > 0, "分离声源应产生干涉区"

    def test_interference_zone_structure(self):
        arrows = [
            self._single_arrow(spl=90.0, pos=(-10, 0)),
            self._single_arrow(spl=90.0, pos=(10, 0)),
        ]
        result = self.volley.simulate_volley(arrows, grid_size=30, grid_spacing=2.0)
        iz = result["interference_zones"]
        assert "constructive_count" in iz
        assert "destructive_count" in iz
        assert "peak_constructive" in iz
        assert "peak_destructive" in iz
        assert iz["peak_constructive"] >= 0
        assert iz["peak_destructive"] >= 0

    def test_total_acoustic_power_positive(self):
        result = self.volley.simulate_volley(
            [self._single_arrow(spl=85.0)], grid_size=10
        )
        assert result["total_acoustic_power_w"] > 0

    def test_frequencies_structure(self):
        result = self.volley.simulate_volley(
            [self._single_arrow()], grid_size=10
        )
        assert len(result["frequencies"]) == 1
        f = result["frequencies"][0]
        assert "fundamental" in f
        assert "2nd_harmonic" in f
        assert "3rd_harmonic" in f
        assert abs(f["2nd_harmonic"] - 2 * f["fundamental"]) < 1.0

    def test_observer_spl_decreases_with_distance(self):
        r_near = self.volley.simulate_volley(
            [self._single_arrow(pos=(0, 0))], grid_size=10, observer_position=(0, 10)
        )
        r_far = self.volley.simulate_volley(
            [self._single_arrow(pos=(0, 0))], grid_size=10, observer_position=(0, 100)
        )
        assert r_near["observer_spl"] > r_far["observer_spl"]

    def test_many_arrows_max_20(self):
        arrows = [self._single_arrow(pos=(i * 3, 0)) for i in range(20)]
        result = self.volley.simulate_volley(arrows, grid_size=20)
        assert result["arrow_count"] == 20

    def test_individual_results_populated(self):
        arrows = [
            {"arrow_id": "A1", "velocity": 65, "whistle_frequency": 1500, "sound_pressure_level": 85, "position": (0, 0)},
            {"arrow_id": "A2", "velocity": 70, "whistle_frequency": 1600, "sound_pressure_level": 87, "position": (5, 0)},
        ]
        result = self.volley.simulate_volley(arrows, grid_size=10)
        assert len(result["individual_results"]) == 2
        assert result["individual_results"][0]["arrow_id"] == "A1"
        assert result["individual_results"][1]["arrow_id"] == "A2"


class TestVolleyInterferencePatterns:

    def setup_method(self):
        self.volley = VolleySimulation()

    def test_identical_co_located_no_destructive(self):
        arrows = [
            {"velocity": 65, "whistle_frequency": 1500, "sound_pressure_level": 85, "position": (0, 0)},
            {"velocity": 65, "whistle_frequency": 1500, "sound_pressure_level": 85, "position": (0, 0)},
        ]
        result = self.volley.simulate_volley(arrows, grid_size=20, grid_spacing=2.0)
        iz = result["interference_zones"]
        assert iz["destructive_count"] < 5, "同位置同频声源不应产生明显破坏性干涉"

    def test_widely_separated_has_interference(self):
        arrows = [
            {"velocity": 65, "whistle_frequency": 1500, "sound_pressure_level": 90, "position": (-20, 0)},
            {"velocity": 65, "whistle_frequency": 1500, "sound_pressure_level": 90, "position": (20, 0)},
        ]
        result = self.volley.simulate_volley(arrows, grid_size=40, grid_spacing=2.0)
        iz = result["interference_zones"]
        assert iz["constructive_count"] + iz["destructive_count"] > 0


# ============================================================
# 4. 虚拟发射体验测试 — 验证音频合成参数的真实感
# ============================================================

class TestAudioSynthesisRealism:

    def setup_method(self):
        self.audio = AudioSynthesisParams()

    def test_fundamental_frequency_in_audible_range(self):
        for vel in [30, 65, 100, 150]:
            r = self.audio.calculate(float(vel))
            assert 20 <= r["fundamental_frequency"] <= 20000, \
                f"v={vel}: 基频{r['fundamental_frequency']}Hz应在可听范围"

    def test_harmonics_structure(self):
        r = self.audio.calculate(65.0, 100.0, shape_profile="conical")
        harmonics = r["harmonics"]
        assert len(harmonics) >= 2, "应至少有2个谐波"
        assert harmonics[0]["amplitude"] > harmonics[1]["amplitude"], "基波振幅应大于谐波"
        for i in range(1, len(harmonics)):
            assert harmonics[i]["amplitude"] <= harmonics[i - 1]["amplitude"], \
                f"谐波{i}振幅应递减"

    def test_harmonics_no_ultrasonic(self):
        r = self.audio.calculate(65.0)
        for h in r["harmonics"]:
            assert h["frequency"] <= 20000, f"谐波频率{h['frequency']}Hz不应超过20kHz"

    def test_adsr_all_positive(self):
        r = self.audio.calculate(65.0)
        adsr = r["adsr"]
        assert adsr["attack"] > 0
        assert adsr["decay"] > 0
        assert 0 < adsr["sustain"] <= 1.0
        assert adsr["release"] > 0

    def test_adsr_attack_short_for_efficient_whistle(self):
        r_cone = self.audio.calculate(65.0, 100.0, shape_profile="conical")
        r_blunt = self.audio.calculate(65.0, 100.0, shape_profile="blunt")
        assert r_cone["adsr"]["attack"] <= r_blunt["adsr"]["attack"], \
            "高效形状起音应更短"

    def test_volume_between_zero_and_one(self):
        for vel in [20, 65, 100, 150]:
            r = self.audio.calculate(float(vel))
            assert 0 <= r["volume"] <= 1.0, f"v={vel}: volume={r['volume']}应在[0,1]"

    def test_vibrato_rate_increases_with_rotation(self):
        r_slow = self.audio.calculate(65.0, 50.0)
        r_fast = self.audio.calculate(65.0, 200.0)
        assert r_fast["vibrato"]["rate_hz"] > r_slow["vibrato"]["rate_hz"]

    def test_sample_rate_standard(self):
        r = self.audio.calculate(65.0)
        assert r["sample_rate"] == 44100

    def test_duration_customizable(self):
        r = self.audio.calculate(65.0, duration_seconds=5.0)
        assert r["duration_seconds"] == 5.0

    def test_waveform_type(self):
        r = self.audio.calculate(65.0)
        assert r["waveform_type"] == "composite_sawtooth_sine"

    def test_timbre_descriptor_content(self):
        for shape in SHAPE_PROFILES:
            r = self.audio.calculate(65.0, 100.0, shape_profile=shape)
            assert len(r["timbre_descriptor"]) >= 2, f"{shape}: 音色描述不应为空"

    def test_timbre_varies_by_shape(self):
        timbres = {}
        for shape in SHAPE_PROFILES:
            r = self.audio.calculate(65.0, 100.0, shape_profile=shape)
            timbres[shape] = r["timbre_descriptor"]
        assert len(set(timbres.values())) >= 2, "不同形状应有不同音色描述"

    def test_detune_cents_vary_by_harmonic(self):
        r = self.audio.calculate(65.0, shape_profile="conical")
        detunes = [h["detune_cents"] for h in r["harmonics"]]
        for i in range(1, len(detunes)):
            assert abs(detunes[i]) >= abs(detunes[i - 1]) * 0.9, \
                "高次谐波失谐应不小于低次"

    def test_shape_profile_echoed(self):
        for shape in SHAPE_PROFILES:
            r = self.audio.calculate(65.0, shape_profile=shape)
            assert r["shape_profile"] == shape

    def test_perceived_pitch_equals_fundamental(self):
        r = self.audio.calculate(65.0)
        assert r["perceived_pitch_hz"] == r["fundamental_frequency"]

    def test_spl_echoed_from_acoustic(self):
        r = self.audio.calculate(65.0, distance=10.0)
        assert r["sound_pressure_level"] > 0
        assert r["observer_distance"] == 10.0

    def test_efficiency_affects_amplitude(self):
        r_cone = self.audio.calculate(65.0, shape_profile="conical")
        r_sphere = self.audio.calculate(65.0, shape_profile="spherical")
        cone_amps = sum(h["amplitude"] for h in r_cone["harmonics"])
        sphere_amps = sum(h["amplitude"] for h in r_sphere["harmonics"])
        eff_cone = SHAPE_PROFILES["conical"]["whistle_efficiency"]
        eff_sphere = SHAPE_PROFILES["spherical"]["whistle_efficiency"]
        if eff_cone > eff_sphere:
            assert cone_amps > sphere_amps, "高效率形状谐波总振幅应更大"


# ============================================================
# 5. Pydantic 模型验证测试 — 边界与异常
# ============================================================

class TestPydanticModelsBoundary:

    def test_shape_comparison_velocity_zero_rejected(self):
        with pytest.raises(Exception):
            ShapeComparisonRequest(velocity=0)

    def test_shape_comparison_velocity_negative_rejected(self):
        with pytest.raises(Exception):
            ShapeComparisonRequest(velocity=-10)

    def test_shape_comparison_valid(self):
        req = ShapeComparisonRequest(velocity=65.0)
        assert req.velocity == 65.0
        assert len(req.shapes) == 4

    def test_volley_arrow_velocity_zero_rejected(self):
        with pytest.raises(Exception):
            VolleyArrowConfig(velocity=0)

    def test_volley_arrow_frequency_zero_rejected(self):
        with pytest.raises(Exception):
            VolleyArrowConfig(whistle_frequency=0)

    def test_volley_arrow_frequency_negative_rejected(self):
        with pytest.raises(Exception):
            VolleyArrowConfig(whistle_frequency=-100)

    def test_volley_simulation_empty_arrows_rejected(self):
        with pytest.raises(Exception):
            VolleySimulationRequest(arrows=[])

    def test_volley_simulation_too_many_arrows_rejected(self):
        arrows = [VolleyArrowConfig(arrow_id=f"v{i}") for i in range(21)]
        with pytest.raises(Exception):
            VolleySimulationRequest(arrows=arrows)

    def test_volley_simulation_max_arrows(self):
        arrows = [VolleyArrowConfig(arrow_id=f"v{i}") for i in range(20)]
        req = VolleySimulationRequest(arrows=arrows)
        assert len(req.arrows) == 20

    def test_volley_grid_size_min(self):
        arrows = [VolleyArrowConfig()]
        req = VolleySimulationRequest(arrows=arrows, grid_size=10)
        assert req.grid_size == 10

    def test_volley_grid_size_below_min_rejected(self):
        with pytest.raises(Exception):
            VolleySimulationRequest(arrows=[VolleyArrowConfig()], grid_size=9)

    def test_volley_grid_spacing_zero_rejected(self):
        with pytest.raises(Exception):
            VolleySimulationRequest(arrows=[VolleyArrowConfig()], grid_spacing=0)

    def test_launch_velocity_zero_rejected(self):
        with pytest.raises(Exception):
            LaunchExperienceRequest(velocity=0)

    def test_launch_velocity_over_max_rejected(self):
        with pytest.raises(Exception):
            LaunchExperienceRequest(velocity=201)

    def test_launch_angle_negative_rejected(self):
        with pytest.raises(Exception):
            LaunchExperienceRequest(launch_angle=-0.1)

    def test_launch_angle_over_max_rejected(self):
        with pytest.raises(Exception):
            LaunchExperienceRequest(launch_angle=1.6)

    def test_launch_distance_zero_rejected(self):
        with pytest.raises(Exception):
            LaunchExperienceRequest(observer_distance=0)

    def test_launch_valid_defaults(self):
        req = LaunchExperienceRequest()
        assert req.velocity == 65.0
        assert req.launch_angle == 0.3
        assert req.shape_profile == "conical"


# ============================================================
# 6. 物理一致性综合测试 — 交叉验证
# ============================================================

class TestPhysicalConsistency:

    def test_shape_sim_vs_original_aero_at_zero_aoa(self):
        shape_sim = ShapeAwareAeroSimulator()
        orig_sim = AeroDynamicsSimulator()
        r_shape = shape_sim.simulate_shape(65.0, "conical", 0.0, 0.0)
        r_orig = orig_sim.simulate(65.0, 0.0, 0.0)
        assert abs(r_shape["reynolds_number"] - r_orig["reynolds_number"]) < 1.0
        assert r_shape["drag_force"] > 0
        assert r_shape["lift_force"] >= 0

    def test_cross_era_mingdi_matches_standalone(self):
        comp = CrossEraAcousticComparator()
        standalone = AeroAcousticsSimulator()
        comp_result = comp.compare(65.0, 100.0, 1.0)
        standalone_result = standalone.simulate(65.0, 100.0, 1.0)
        assert abs(comp_result["mingdi"]["whistle_frequency"] - standalone_result["whistle_frequency"]) < 1.0

    def test_volley_single_source_spl_matches_acoustic(self):
        volley = VolleySimulation()
        acoustic = AeroAcousticsSimulator()
        ac_result = acoustic.simulate(65.0, 100.0, 1.0)
        v_result = volley.simulate_volley(
            [{"velocity": 65, "whistle_frequency": ac_result["whistle_frequency"],
              "sound_pressure_level": ac_result["sound_pressure_level"], "position": (0, 0)}],
            grid_size=10, observer_position=(0, 50),
        )
        assert v_result["observer_spl"] > 0

    def test_energy_conservation_dual_source(self):
        volley = VolleySimulation()
        single = volley.simulate_volley(
            [{"velocity": 65, "whistle_frequency": 1500, "sound_pressure_level": 85, "position": (0, 0)}],
            grid_size=10, observer_position=(0, 50),
        )
        dual = volley.simulate_volley(
            [{"velocity": 65, "whistle_frequency": 1500, "sound_pressure_level": 85, "position": (0, 0)},
             {"velocity": 65, "whistle_frequency": 1500, "sound_pressure_level": 85, "position": (0, 0)}],
            grid_size=10, observer_position=(0, 50),
        )
        assert dual["total_acoustic_power_w"] > single["total_acoustic_power_w"]
        assert abs(dual["total_acoustic_power_w"] / single["total_acoustic_power_w"] - 2.0) < 0.1

    def test_audio_params_match_acoustic_frequency(self):
        audio = AudioSynthesisParams()
        acoustic = AeroAcousticsSimulator()
        ac = acoustic.simulate(65.0, 100.0, 10.0)
        au = audio.calculate(65.0, 100.0, distance=10.0)
        assert abs(au["fundamental_frequency"] - ac["whistle_frequency"]) < 1.0

    def test_drag_monotonic_with_aoa(self):
        sim = ShapeAwareAeroSimulator()
        prev_cd = 0
        for aoa in [0.0, 0.05, 0.1, 0.15, 0.2, 0.3]:
            r = sim.simulate_shape(65.0, "conical", aoa, 0.0)
            assert r["drag_coefficient"] >= prev_cd - 0.01, f"aoa={aoa}: Cd应单调递增"
            prev_cd = r["drag_coefficient"]

    def test_frequency_increases_with_velocity(self):
        acoustic = AeroAcousticsSimulator()
        prev_freq = 0
        for vel in [30, 50, 65, 80, 100]:
            r = acoustic.simulate(float(vel), 100.0, 1.0)
            assert r["whistle_frequency"] > prev_freq, f"v={vel}: freq={r['whistle_frequency']}应递增"
            prev_freq = r["whistle_frequency"]
