"""
test_credibility.py
======================
CredibilityCalculator のユニットテスト。

テスト対象:
  - PDER (Method Score) ヒューリスティックスコアリング
  - CSI ヒューリスティックスコアリング
  - CR 計算（6スコアの積）
  - エッジケース・境界値テスト
"""

import pytest
from credibility_calculator import CredibilityCalculator


class TestPDERHeuristic:
    """PDER (Method Score) ヒューリスティックのテスト."""

    def setup_method(self):
        self.calc = CredibilityCalculator(use_api=False)

    # ---- Tracing methods: highest scores ----

    def test_tracer_study(self):
        score = self.calc.score_pder("Tracer study")
        assert 0.80 <= score <= 0.95, f"Tracer study should be 0.80-0.95, got {score}"

    def test_various_tracing(self):
        score = self.calc.score_pder("Various tracing")
        assert 0.85 <= score <= 0.95

    def test_anterograde_tracer(self):
        score = self.calc.score_pder("anterograde tracer (BDA)")
        assert 0.85 <= score <= 0.95

    def test_retrograde_tracer(self):
        score = self.calc.score_pder("retrograde tracer (FG)")
        assert 0.85 <= score <= 0.95

    def test_viral_tracing(self):
        score = self.calc.score_pder("viral tracing (AAV)")
        assert 0.80 <= score <= 0.90

    def test_hrp_method(self):
        score = self.calc.score_pder("HRP injection")
        assert 0.80 <= score <= 0.90

    # ---- Electrophysiology: medium-high ----

    def test_electrophysiology(self):
        score = self.calc.score_pder("Electrophys")
        assert 0.55 <= score <= 0.75

    def test_patch_clamp(self):
        score = self.calc.score_pder("patch clamp recording")
        assert 0.55 <= score <= 0.75

    # ---- Optogenetics: medium-high ----

    def test_optogenetics(self):
        score = self.calc.score_pder("optogenetics")
        assert 0.55 <= score <= 0.75

    def test_opto_chemo(self):
        score = self.calc.score_pder("Opto/Chemo")
        assert 0.55 <= score <= 0.75

    def test_channelrhodopsin(self):
        score = self.calc.score_pder("channelrhodopsin-assisted circuit mapping")
        assert 0.55 <= score <= 0.75

    # ---- Imaging methods: medium ----

    def test_fmri(self):
        score = self.calc.score_pder("fMRI")
        assert 0.30 <= score <= 0.50

    def test_resting_state_fmri(self):
        score = self.calc.score_pder("resting-state functional magnetic resonance imaging")
        assert 0.30 <= score <= 0.50

    def test_dti_tractography(self):
        score = self.calc.score_pder("DTI/tractography")
        assert 0.35 <= score <= 0.55

    def test_diffusion_tensor(self):
        score = self.calc.score_pder("diffusion tensor imaging (DTI)")
        assert 0.35 <= score <= 0.55

    # ---- Secondary sources: lower ----

    def test_review(self):
        score = self.calc.score_pder("Review")
        assert 0.20 <= score <= 0.40

    def test_unspecified(self):
        score = self.calc.score_pder("Unspecified")
        assert 0.20 <= score <= 0.40

    def test_textbook(self):
        score = self.calc.score_pder("Textbook reference")
        assert 0.15 <= score <= 0.35

    # ---- Review papers that describe tracing → adjusted score ----

    def test_review_of_tracing(self):
        """Review papers referencing tracing get adjusted down from tracing score."""
        score_exp = self.calc.score_pder("Tracer study", "Experimental results")
        score_rev = self.calc.score_pder("Tracer study", "Review")
        assert score_rev < score_exp, "Review of tracing should score lower than experimental"

    # ---- Edge cases ----

    def test_empty_method(self):
        score = self.calc.score_pder("")
        assert score == 0.0

    def test_none_method(self):
        score = self.calc.score_pder(None)
        assert score == 0.0

    def test_unknown_method(self):
        """Unknown method should get a default score, not crash."""
        score = self.calc.score_pder("Completely Novel Method XYZ-2000")
        assert 0.0 <= score <= 1.0

    def test_score_always_in_range(self):
        """All scores should be in [0.0, 1.0]."""
        methods = [
            "Tracer study", "fMRI", "optogenetics", "Review", "",
            "Electrophys", "DTI/tractography", "Unspecified",
            "resting-state fMRI", "Various tracing",
        ]
        for m in methods:
            score = self.calc.score_pder(m)
            assert 0.0 <= score <= 1.0, f"Out of range for '{m}': {score}"


class TestCSIHeuristic:
    """CSI (Citation Sentiment Index) ヒューリスティックのテスト."""

    def setup_method(self):
        self.calc = CredibilityCalculator(use_api=False)

    def test_known_seminal_paper(self):
        """Known seminal papers should have high CSI."""
        score = self.calc.score_csi("Amaral, 1991")
        assert score >= 0.80

    def test_known_high_impact(self):
        score = self.calc.score_csi("Wei, 2016")
        assert score >= 0.70

    def test_new_paper_default(self):
        """Very recent papers default to neutral."""
        score = self.calc.score_csi("NewAuthor, 2025")
        assert 0.45 <= score <= 0.55

    def test_older_paper_default(self):
        """Older unknown papers that are still cited → slightly positive."""
        score = self.calc.score_csi("OldAuthor, 1995")
        assert 0.55 <= score <= 0.70

    def test_invalid_reference(self):
        score = self.calc.score_csi("author, year")
        assert score <= 0.20

    def test_error_reference(self):
        score = self.calc.score_csi("#N/A")
        assert score <= 0.20

    def test_empty_reference(self):
        score = self.calc.score_csi("")
        assert score <= 0.20

    def test_score_always_in_range(self):
        refs = ["Amaral, 1991", "Unknown, 2020", "", "author, year", "#N/A"]
        for r in refs:
            score = self.calc.score_csi(r)
            assert 0.0 <= score <= 1.0, f"Out of range for '{r}': {score}"


class TestCRCalculation:
    """CR (Credibility Rating) = 6スコアの積のテスト."""

    def test_all_ones(self):
        cr = CredibilityCalculator.compute_cr(1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
        assert cr == 1.0

    def test_all_zeros(self):
        cr = CredibilityCalculator.compute_cr(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        assert cr == 0.0

    def test_one_zero_makes_cr_zero(self):
        """If any single score is 0, CR must be 0."""
        cr = CredibilityCalculator.compute_cr(1.0, 1.0, 1.0, 1.0, 1.0, 0.0)
        assert cr == 0.0

    def test_known_example_from_data(self):
        """Verified against actual data: Row 176 of wbConnections."""
        cr = CredibilityCalculator.compute_cr(
            source_region=1.0,
            receiver_region=1.0,
            csi=0.95,
            literature_type=1.0,
            taxon=0.5,
            pder=0.4,
        )
        assert abs(cr - 0.19) < 0.001, f"Expected 0.190, got {cr}"

    def test_known_example_2(self):
        """Verified: Row 319."""
        cr = CredibilityCalculator.compute_cr(1.0, 1.0, 0.95, 1.0, 0.6, 0.8)
        assert abs(cr - 0.456) < 0.001

    def test_known_example_3(self):
        """Verified: Row 181."""
        cr = CredibilityCalculator.compute_cr(1.0, 1.0, 0.95, 0.5, 0.5, 0.3)
        assert abs(cr - 0.0712) < 0.001

    def test_symmetric(self):
        """CR should not depend on which scores are source vs receiver."""
        cr1 = CredibilityCalculator.compute_cr(0.8, 0.5, 0.7, 0.6, 0.4, 0.9)
        cr2 = CredibilityCalculator.compute_cr(0.5, 0.8, 0.7, 0.6, 0.4, 0.9)
        assert abs(cr1 - cr2) < 0.0001

    def test_cr_precision(self):
        """CR should be rounded to 4 decimal places."""
        cr = CredibilityCalculator.compute_cr(0.3, 0.3, 0.3, 0.3, 0.3, 0.3)
        # 0.3^6 = 0.000729
        assert cr == 0.0007

    def test_monotonic_increase(self):
        """Increasing any score should increase CR."""
        base = CredibilityCalculator.compute_cr(0.5, 0.5, 0.5, 0.5, 0.5, 0.5)
        higher = CredibilityCalculator.compute_cr(0.5, 0.5, 0.5, 0.5, 0.5, 0.8)
        assert higher > base


class TestPDERMethodOrdering:
    """手法間のスコア順序が正しいことを検証."""

    def setup_method(self):
        self.calc = CredibilityCalculator(use_api=False)

    def test_tracing_higher_than_electrophys(self):
        tracer = self.calc.score_pder("Tracer study")
        electro = self.calc.score_pder("Electrophys")
        assert tracer > electro

    def test_electrophys_higher_than_fmri(self):
        electro = self.calc.score_pder("Electrophys")
        fmri = self.calc.score_pder("fMRI")
        assert electro > fmri

    def test_fmri_higher_than_review(self):
        fmri = self.calc.score_pder("fMRI")
        review = self.calc.score_pder("Review")
        assert fmri > review

    def test_experimental_higher_than_review_same_method(self):
        exp = self.calc.score_pder("Tracer study", "Experimental results")
        rev = self.calc.score_pder("Tracer study", "Review")
        assert exp > rev

    def test_optogenetics_comparable_to_electrophys(self):
        opto = self.calc.score_pder("optogenetics")
        electro = self.calc.score_pder("Electrophys")
        assert abs(opto - electro) < 0.15, "Opto and electrophys should be similar"
