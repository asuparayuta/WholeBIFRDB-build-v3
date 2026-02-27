"""
test_converter.py
====================
ManualToBdbraConverter のユニットテスト。

テスト対象:
  - CSV読み込み・バリデーション
  - 参照整合性チェック
  - 派生フィールド生成
  - Literature type score
  - エッジケース
"""

import csv
import pytest
from pathlib import Path

from schema import ConnectionRecord, ReferenceRecord, WB_CONNECTIONS_COLUMNS
from manual_to_bdbra_converter import ManualToBdbraConverter
from credibility_calculator import CredibilityCalculator


class TestLoadReferences:
    """wbReferences CSV の読み込みテスト."""

    def test_load_valid_references(self, converter, sample_references_csv):
        count = converter.load_references(sample_references_csv)
        assert count == 3
        assert "Smith, 2020" in converter.references
        assert "Tanaka, 2019" in converter.references
        assert "Lee, 2023" in converter.references

    def test_reference_doi_loaded(self, converter, sample_references_csv):
        converter.load_references(sample_references_csv)
        ref = converter.references["Smith, 2020"]
        assert ref.doi == "10.1234/test.2020.001"

    def test_reference_journal_loaded(self, converter, sample_references_csv):
        converter.load_references(sample_references_csv)
        ref = converter.references["Smith, 2020"]
        assert ref.journal == "Journal of Neuroscience"

    def test_load_missing_file(self, converter):
        with pytest.raises(FileNotFoundError):
            converter.load_references("/nonexistent/path.csv")

    def test_load_references_missing_doi_warning(
        self, converter, references_with_missing_doi_csv
    ):
        converter.load_references(references_with_missing_doi_csv)
        # Should have a warning about missing DOI
        assert any("DOI" in w.message or "doi" in w.message for w in converter.warnings)


class TestLoadConnections:
    """wbConnections CSV の読み込みテスト."""

    def test_load_valid_connections(self, converter, sample_connections_csv):
        count = converter.load_connections(sample_connections_csv)
        assert count == 3

    def test_connection_fields_parsed(self, converter, sample_connections_csv):
        converter.load_connections(sample_connections_csv)
        conn = converter.connections[0]
        assert conn.sender_cid == "CA1"
        assert conn.receiver_cid == "Sub"
        assert conn.reference_id == "Smith, 2020"
        assert conn.measurement_method == "Tracer study"

    def test_connection_scores_parsed(self, converter, sample_connections_csv):
        converter.load_connections(sample_connections_csv)
        conn = converter.connections[0]
        assert conn.source_region_score == 1.0
        assert conn.receiver_region_score == 1.0
        assert conn.taxon_score == 0.6

    def test_default_contributor_applied(self, converter, sample_connections_csv):
        converter.load_connections(sample_connections_csv)
        assert converter.connections[0].contributor == "TestContributor"

    def test_default_project_id_applied(self, converter, sample_connections_csv):
        converter.load_connections(sample_connections_csv)
        assert converter.connections[0].project_id == "TEST01"

    def test_load_malformed_connections(self, converter, malformed_connections_csv):
        converter.load_connections(malformed_connections_csv)
        # Should have errors for missing required fields
        assert len(converter.errors) >= 2  # missing sender and missing receiver


class TestCrossValidation:
    """参照整合性チェックのテスト."""

    def test_all_refs_found(
        self, converter, sample_references_csv, sample_connections_csv
    ):
        converter.load_references(sample_references_csv)
        converter.load_connections(sample_connections_csv)
        missing = converter.cross_validate()
        assert len(missing) == 0

    def test_missing_ref_detected(
        self, converter, sample_references_csv, sample_connections_csv
    ):
        converter.load_references(sample_references_csv)
        converter.load_connections(sample_connections_csv)
        # Add a connection with non-existent reference
        from schema import ConnectionRecord
        conn = ConnectionRecord(
            sender_cid="X1",
            receiver_cid="X2",
            reference_id="Nonexistent, 2099",
        )
        converter.connections.append(conn)
        missing = converter.cross_validate()
        assert len(missing) == 1
        assert "Nonexistent, 2099" in missing[0].message


class TestDerivedFields:
    """派生フィールドの生成テスト."""

    def test_combined_search(self, converter, sample_references_csv):
        converter.load_references(sample_references_csv)
        conn = ConnectionRecord(sender_cid="CA1", receiver_cid="Sub")
        converter.compute_derived_fields(conn)
        assert conn.combined_search == "CA1Sub"

    def test_reference_id_bracket(self, converter, sample_references_csv):
        converter.load_references(sample_references_csv)
        conn = ConnectionRecord(
            sender_cid="CA1", receiver_cid="Sub", reference_id="Smith, 2020"
        )
        converter.compute_derived_fields(conn)
        assert conn.reference_id_bracket == "[Smith, 2020]"

    def test_display_string(self, converter, sample_references_csv):
        converter.load_references(sample_references_csv)
        conn = ConnectionRecord(
            sender_cid="CA1", receiver_cid="Sub", reference_id="Smith, 2020"
        )
        converter.compute_derived_fields(conn)
        assert "Sub" in conn.display_string
        assert "[Smith, 2020]" in conn.display_string

    def test_journal_name_from_reference(self, converter, sample_references_csv):
        converter.load_references(sample_references_csv)
        conn = ConnectionRecord(
            sender_cid="CA1", receiver_cid="Sub", reference_id="Smith, 2020"
        )
        converter.compute_derived_fields(conn)
        assert conn.journal_name == "Journal of Neuroscience"


class TestLiteratureTypeScore:
    """Literature Type Score のテスト."""

    def test_experimental_results(self):
        score = ManualToBdbraConverter.compute_literature_type_score(
            "Experimental results"
        )
        assert score == 1.0

    def test_review(self):
        score = ManualToBdbraConverter.compute_literature_type_score("Review")
        assert score == 0.8

    def test_textbook(self):
        score = ManualToBdbraConverter.compute_literature_type_score("Textbook")
        assert score == 0.5

    def test_hypothesis(self):
        score = ManualToBdbraConverter.compute_literature_type_score("Hypothesis")
        assert score == 0.3

    def test_error_type(self):
        score = ManualToBdbraConverter.compute_literature_type_score(
            "#Error: Reference ID"
        )
        assert score == 0.0

    def test_empty_type(self):
        score = ManualToBdbraConverter.compute_literature_type_score("")
        assert score == 0.0

    def test_case_insensitive(self):
        score1 = ManualToBdbraConverter.compute_literature_type_score("review")
        score2 = ManualToBdbraConverter.compute_literature_type_score("REVIEW")
        assert score1 == score2


class TestFullConversion:
    """変換パイプライン全体のテスト."""

    def test_full_conversion_dry_run(
        self, converter, sample_references_csv, sample_connections_csv, tmp_dir
    ):
        converter.load_references(sample_references_csv)
        converter.load_connections(sample_connections_csv)
        records = converter.convert(skip_credibility=True)
        assert len(records) == 3
        # Derived fields should be computed
        assert records[0].combined_search == "CA1Sub"

    def test_full_conversion_with_credibility(
        self, converter, sample_references_csv, sample_connections_csv
    ):
        converter.load_references(sample_references_csv)
        converter.load_connections(sample_connections_csv)
        records = converter.convert(skip_credibility=False)

        # PDER should be calculated for "Tracer study"
        assert records[0].method_score_pder > 0.0
        # CSI should be calculated
        assert records[0].citation_sentiment_index > 0.0
        # Literature type score
        assert records[0].literature_type_score > 0.0

    def test_cr_computed_correctly(
        self, converter, sample_references_csv, sample_connections_csv
    ):
        converter.load_references(sample_references_csv)
        converter.load_connections(sample_connections_csv)
        records = converter.convert(skip_credibility=False)

        for rec in records:
            expected_cr = (
                rec.source_region_score
                * rec.receiver_region_score
                * rec.citation_sentiment_index
                * rec.literature_type_score
                * rec.taxon_score
                * rec.method_score_pder
            )
            assert abs(rec.credibility_rating - round(expected_cr, 4)) < 0.001, (
                f"CR mismatch for {rec.sender_cid}→{rec.receiver_cid}: "
                f"expected {expected_cr:.4f}, got {rec.credibility_rating}"
            )


class TestBdbraCsvOutput:
    """BDBRA CSV 出力のテスト."""

    def test_write_csv(
        self, converter, sample_references_csv, sample_connections_csv, tmp_dir
    ):
        converter.load_references(sample_references_csv)
        converter.load_connections(sample_connections_csv)
        converter.convert(skip_credibility=True)

        output_path = str(tmp_dir / "output.csv")
        rows = converter.write_bdbra_csv(output_path)
        assert rows == 3
        assert Path(output_path).exists()

    def test_csv_has_correct_headers(
        self, converter, sample_references_csv, sample_connections_csv, tmp_dir
    ):
        converter.load_references(sample_references_csv)
        converter.load_connections(sample_connections_csv)
        converter.convert(skip_credibility=True)

        output_path = str(tmp_dir / "output.csv")
        converter.write_bdbra_csv(output_path)

        with open(output_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader)
        assert len(headers) == len(WB_CONNECTIONS_COLUMNS)

    def test_csv_roundtrip(
        self, converter, sample_references_csv, sample_connections_csv, tmp_dir
    ):
        """CSV出力→再読み込みで値が保持されることを検証."""
        converter.load_references(sample_references_csv)
        converter.load_connections(sample_connections_csv)
        converter.convert(skip_credibility=False)

        output_path = str(tmp_dir / "roundtrip.csv")
        converter.write_bdbra_csv(output_path)

        # Re-load
        converter2 = ManualToBdbraConverter(
            credibility_calc=CredibilityCalculator(use_api=False),
        )
        converter2.load_connections(output_path)

        assert len(converter2.connections) == 3
        assert converter2.connections[0].sender_cid == "CA1"
        assert converter2.connections[0].receiver_cid == "Sub"

    def test_report_generation(
        self, converter, sample_references_csv, sample_connections_csv
    ):
        converter.load_references(sample_references_csv)
        converter.load_connections(sample_connections_csv)
        converter.convert(skip_credibility=True)
        report = converter.get_report()
        assert report["references_loaded"] == 3
        assert report["connections_loaded"] == 3
        assert report["error_count"] == 0
