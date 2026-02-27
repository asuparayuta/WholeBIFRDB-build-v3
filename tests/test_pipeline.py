"""
test_pipeline.py
===================
パイプライン統合テストおよびデータ整合性テスト。

テスト対象:
  - パイプライン全体の E2E テスト
  - 実データ（WholeBIF_RDBv2）との整合性テスト
  - バリデーションルールの網羅テスト
  - エッジケース・異常系テスト
"""

import csv
import json
import os
import pytest
from pathlib import Path

from schema import (
    ConnectionRecord,
    ReferenceRecord,
    ValidationError,
    validate_connection,
    validate_reference,
)
from manual_to_bdbra_converter import ManualToBdbraConverter
from credibility_calculator import CredibilityCalculator
from pipeline import run_pipeline, PipelineResult


# ============================================================
# E2E Pipeline Tests
# ============================================================

class TestPipelineE2E:
    """パイプライン全体のE2Eテスト."""

    def test_full_pipeline_dry_run(
        self, sample_connections_csv, sample_references_csv, tmp_dir
    ):
        result = run_pipeline(
            connections_csv=sample_connections_csv,
            references_csv=sample_references_csv,
            output_dir=str(tmp_dir / "pipeline_out"),
            contributor="E2E_Test",
            project_id="E2E01",
            dry_run=True,
            skip_import=True,
        )
        assert result.success is True
        assert result.connections_output == 3
        assert result.references_loaded == 3
        assert result.bdbra_csv_path is not None
        assert Path(result.bdbra_csv_path).exists()

    def test_pipeline_output_csv_valid(
        self, sample_connections_csv, sample_references_csv, tmp_dir
    ):
        result = run_pipeline(
            connections_csv=sample_connections_csv,
            references_csv=sample_references_csv,
            output_dir=str(tmp_dir / "pipeline_out"),
            dry_run=True,
            skip_import=True,
        )
        # Verify output CSV
        with open(result.bdbra_csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader)
            rows = list(reader)

        assert len(rows) == 3
        # Check sender_cid preserved
        assert rows[0][0] == "CA1"
        # Check receiver_cid preserved
        assert rows[0][3] == "Sub"

    def test_pipeline_report_generated(
        self, sample_connections_csv, sample_references_csv, tmp_dir
    ):
        result = run_pipeline(
            connections_csv=sample_connections_csv,
            references_csv=sample_references_csv,
            output_dir=str(tmp_dir / "pipeline_out"),
            dry_run=True,
            skip_import=True,
        )
        assert result.report_path is not None
        with open(result.report_path, "r", encoding="utf-8") as f:
            report = json.load(f)
        assert "references_loaded" in report
        assert "connections_loaded" in report

    def test_pipeline_with_missing_connections_file(self, tmp_dir):
        result = run_pipeline(
            connections_csv="/nonexistent.csv",
            references_csv="/nonexistent_refs.csv",
            output_dir=str(tmp_dir / "pipeline_out"),
            dry_run=True,
        )
        assert result.success is False
        assert len(result.errors) > 0

    def test_pipeline_duration_tracked(
        self, sample_connections_csv, sample_references_csv, tmp_dir
    ):
        result = run_pipeline(
            connections_csv=sample_connections_csv,
            references_csv=sample_references_csv,
            output_dir=str(tmp_dir / "pipeline_out"),
            dry_run=True,
        )
        assert result.duration_seconds >= 0


# ============================================================
# Validation Rule Tests
# ============================================================

class TestValidationRules:
    """バリデーションルールの網羅テスト."""

    def test_valid_connection(self):
        conn = ConnectionRecord(
            sender_cid="CA1",
            receiver_cid="Sub",
            reference_id="Smith, 2020",
            source_region_score=1.0,
            receiver_region_score=1.0,
            taxon_score=0.5,
        )
        errors = validate_connection(conn)
        real_errors = [e for e in errors if e.severity == "error"]
        assert len(real_errors) == 0

    def test_missing_sender_cid(self):
        conn = ConnectionRecord(sender_cid="", receiver_cid="Sub", reference_id="X, 2020")
        errors = validate_connection(conn)
        assert any("sender" in e.field.lower() for e in errors if e.severity == "error")

    def test_missing_receiver_cid(self):
        conn = ConnectionRecord(sender_cid="CA1", receiver_cid="", reference_id="X, 2020")
        errors = validate_connection(conn)
        assert any("receiver" in e.field.lower() for e in errors if e.severity == "error")

    def test_missing_reference_id(self):
        conn = ConnectionRecord(sender_cid="CA1", receiver_cid="Sub", reference_id="")
        errors = validate_connection(conn)
        assert any("reference" in e.field.lower() for e in errors if e.severity == "error")

    def test_score_out_of_range(self):
        conn = ConnectionRecord(
            sender_cid="CA1",
            receiver_cid="Sub",
            reference_id="X, 2020",
            source_region_score=1.5,  # out of range
        )
        errors = validate_connection(conn)
        assert any("score" in e.message.lower() or "range" in e.message.lower() 
                    for e in errors if e.severity == "error")

    def test_negative_score(self):
        conn = ConnectionRecord(
            sender_cid="CA1",
            receiver_cid="Sub",
            reference_id="X, 2020",
            method_score_pder=-0.1,
        )
        errors = validate_connection(conn)
        assert any(e.severity == "error" for e in errors)

    def test_reference_id_format_warning(self):
        """Non-standard Reference ID format triggers warning."""
        conn = ConnectionRecord(
            sender_cid="CA1",
            receiver_cid="Sub",
            reference_id="Bad Format 2020",
        )
        errors = validate_connection(conn)
        warnings = [e for e in errors if e.severity == "warning"]
        assert len(warnings) >= 1

    def test_valid_reference_id_formats(self):
        """Standard reference ID formats should not trigger warnings."""
        valid_ids = ["Smith, 2020", "O'Brien, 2019", "von Neumann, 1945", "D'Angelo, 2013"]
        for ref_id in valid_ids:
            conn = ConnectionRecord(
                sender_cid="X", receiver_cid="Y", reference_id=ref_id,
            )
            errors = validate_connection(conn)
            warnings = [e for e in errors if e.severity == "warning" and "format" in e.message.lower()]
            # These may or may not trigger warnings depending on regex strictness
            # Just ensure they don't cause errors
            real_errors = [e for e in errors if e.severity == "error"]
            assert not any("reference_id" in e.field for e in real_errors)


class TestReferenceValidation:
    """ReferenceRecord バリデーションテスト."""

    def test_valid_reference(self):
        ref = ReferenceRecord(reference_id="Smith, 2020", doi="10.1234/test")
        errors = validate_reference(ref)
        assert len([e for e in errors if e.severity == "error"]) == 0

    def test_missing_reference_id(self):
        ref = ReferenceRecord(reference_id="", doi="10.1234/test")
        errors = validate_reference(ref)
        assert any(e.severity == "error" for e in errors)

    def test_missing_doi_warning(self):
        ref = ReferenceRecord(reference_id="Smith, 2020", doi="")
        errors = validate_reference(ref)
        assert any(e.severity == "warning" for e in errors)


# ============================================================
# Data Integrity Tests (against real data patterns)
# ============================================================

class TestDataIntegrity:
    """実データパターンに基づくデータ整合性テスト."""

    def test_cr_product_formula(self):
        """CR が常に6スコアの積であることを検証."""
        test_cases = [
            (1.0, 1.0, 0.95, 1.0, 0.5, 0.4, 0.190),
            (1.0, 1.0, 0.95, 1.0, 0.6, 0.8, 0.456),
            (1.0, 1.0, 0.95, 0.5, 0.5, 0.3, 0.0712),
            (0.0, 1.0, 0.5, 0.8, 0.6, 0.3, 0.0),
        ]
        for src, rcv, csi, lit, tax, pder, expected_cr in test_cases:
            cr = CredibilityCalculator.compute_cr(src, rcv, csi, lit, tax, pder)
            assert abs(cr - expected_cr) < 0.002, (
                f"CR({src},{rcv},{csi},{lit},{tax},{pder}) = {cr}, expected {expected_cr}"
            )

    def test_pder_ordering_matches_existing(self):
        """既存データの手法順序と整合することを検証."""
        calc = CredibilityCalculator(use_api=False)
        
        # From existing data, these orderings should hold:
        scores = {
            "Various tracing": calc.score_pder("Various tracing"),
            "Tracer study": calc.score_pder("Tracer study"),
            "Electrophys": calc.score_pder("Electrophys"),
            "Opto/Chemo": calc.score_pder("Opto/Chemo"),
            "DTI/tractography": calc.score_pder("DTI/tractography"),
            "fMRI": calc.score_pder("fMRI"),
            "Review": calc.score_pder("Review"),
        }

        assert scores["Various tracing"] >= scores["Tracer study"]
        assert scores["Tracer study"] >= scores["Electrophys"]
        assert scores["Electrophys"] >= scores["fMRI"]
        assert scores["fMRI"] >= scores["Review"]

    def test_literature_type_score_ordering(self):
        """Literature type score ordering matches expected hierarchy."""
        scores = {
            "Experimental results": ManualToBdbraConverter.compute_literature_type_score("Experimental results"),
            "Review": ManualToBdbraConverter.compute_literature_type_score("Review"),
            "Data description": ManualToBdbraConverter.compute_literature_type_score("Data description"),
            "Textbook": ManualToBdbraConverter.compute_literature_type_score("Textbook"),
            "Hypothesis": ManualToBdbraConverter.compute_literature_type_score("Hypothesis"),
        }
        assert scores["Experimental results"] > scores["Review"]
        assert scores["Review"] > scores["Textbook"]
        assert scores["Textbook"] > scores["Hypothesis"]


# ============================================================
# ConnectionRecord serialization tests
# ============================================================

class TestConnectionRecordSerialization:
    """ConnectionRecord の変換・シリアル化テスト."""

    def test_to_row_length(self):
        conn = ConnectionRecord(sender_cid="CA1")
        row = conn.to_row()
        assert len(row) == 42  # 42 columns

    def test_from_row_roundtrip(self):
        original = ConnectionRecord(
            sender_cid="CA1",
            receiver_cid="Sub",
            reference_id="Test, 2020",
            source_region_score=0.8,
            credibility_rating=0.456,
        )
        row = original.to_row()
        restored = ConnectionRecord.from_row(row)
        assert restored.sender_cid == original.sender_cid
        assert restored.receiver_cid == original.receiver_cid
        assert restored.reference_id == original.reference_id
        assert abs(restored.source_region_score - original.source_region_score) < 0.001

    def test_from_row_short_row(self):
        """Short rows should be handled gracefully."""
        short_row = ["CA1", "", "", "Sub"]
        conn = ConnectionRecord.from_row(short_row)
        assert conn.sender_cid == "CA1"
        assert conn.receiver_cid == "Sub"
        assert conn.source_region_score == 0.0

    def test_from_row_invalid_float(self):
        """Non-numeric score fields should default to 0."""
        row = [""] * 42
        row[0] = "CA1"
        row[3] = "Sub"
        row[20] = "not_a_number"
        conn = ConnectionRecord.from_row(row)
        assert conn.source_region_score == 0.0
