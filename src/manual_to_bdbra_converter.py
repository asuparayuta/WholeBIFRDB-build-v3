"""
manual_to_bdbra_converter.py
===============================
人手設計データ（BRAES / 既存WholeBIF）を BDBRA CSV に変換するコンバータ。

パイプライン図の赤枠「manual_to_bdbra_converter.py（仮）」に対応。

入力:
  - Google Spreadsheet からエクスポートされた wbConnections CSV（新規行）
  - Google Spreadsheet からエクスポートされた wbReferences CSV（新規行）

出力:
  - BDBRA CSV（信頼度計算済み、import_bdbra_into_wholebif.py で取り込み可能）

Usage:
    python manual_to_bdbra_converter.py \\
        --connections new_connections.csv \\
        --references new_references.csv \\
        --output bdbra_output.csv \\
        [--contributor "Contributor Name"] \\
        [--project-id "PROJECT01"] \\
        [--dry-run]
"""

import argparse
import csv
import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional

from schema import (
    ConnectionRecord,
    ReferenceRecord,
    ValidationError,
    WB_CONNECTIONS_COLUMNS,
    validate_connection,
    validate_reference,
)
from credibility_calculator import CredibilityCalculator

logger = logging.getLogger(__name__)


class ConversionError(Exception):
    """Raised when conversion fails."""
    pass


class ManualToBdbraConverter:
    """
    Converts manually designed neuroscience data to BDBRA CSV format.

    Responsibilities:
    1. Load & validate new wbConnections and wbReferences from CSV
    2. Cross-reference: ensure every Connection's Reference ID exists in References
    3. Compute derived fields (display_string, combined_search, reference_id_bracket)
    4. Calculate credibility scores (PDER, CSI, CR) via CredibilityCalculator
    5. Output BDBRA CSV ready for import
    """

    def __init__(
        self,
        credibility_calc: Optional[CredibilityCalculator] = None,
        contributor: str = "",
        project_id: str = "",
    ):
        self.credibility_calc = credibility_calc or CredibilityCalculator()
        self.contributor = contributor
        self.project_id = project_id
        self.references: dict[str, ReferenceRecord] = {}
        self.connections: list[ConnectionRecord] = []
        self.errors: list[ValidationError] = []
        self.warnings: list[ValidationError] = []

    # ================================================================
    # Loading
    # ================================================================

    def load_references(self, csv_path: str) -> int:
        """Load reference records from CSV. Returns count loaded."""
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"References CSV not found: {csv_path}")

        count = 0
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader)  # skip header
            for row_num, row in enumerate(reader, start=2):
                if not any(cell.strip() for cell in row):
                    continue  # skip empty rows
                ref = ReferenceRecord.from_row(row)
                errs = validate_reference(ref)
                for e in errs:
                    e.message = f"Row {row_num}: {e.message}"
                    if e.severity == "error":
                        self.errors.append(e)
                    else:
                        self.warnings.append(e)

                if ref.reference_id:
                    self.references[ref.reference_id] = ref
                    count += 1

        logger.info(f"Loaded {count} references from {csv_path}")
        return count

    def load_connections(self, csv_path: str) -> int:
        """Load connection records from CSV. Returns count loaded."""
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"Connections CSV not found: {csv_path}")

        count = 0
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader)  # skip header
            for row_num, row in enumerate(reader, start=2):
                if not any(cell.strip() for cell in row):
                    continue  # skip empty rows

                # Pad row to expected length
                while len(row) < len(WB_CONNECTIONS_COLUMNS):
                    row.append("")

                conn = ConnectionRecord.from_row(row)

                # Apply defaults
                if not conn.contributor and self.contributor:
                    conn.contributor = self.contributor
                if not conn.project_id and self.project_id:
                    conn.project_id = self.project_id

                errs = validate_connection(conn)
                for e in errs:
                    e.message = f"Row {row_num}: {e.message}"
                    if e.severity == "error":
                        self.errors.append(e)
                    else:
                        self.warnings.append(e)

                self.connections.append(conn)
                count += 1

        logger.info(f"Loaded {count} connections from {csv_path}")
        return count

    # ================================================================
    # Cross-reference validation
    # ================================================================

    def cross_validate(self) -> list[ValidationError]:
        """Check that all connection Reference IDs exist in references."""
        missing = []
        for i, conn in enumerate(self.connections):
            ref_id = conn.reference_id
            if ref_id and ref_id not in self.references:
                if ref_id not in ("author, year", "#N/A", ""):
                    err = ValidationError(
                        "reference_id",
                        f"Connection #{i+1}: Reference '{ref_id}' not found in wbReferences",
                        severity="warning",
                    )
                    self.warnings.append(err)
                    missing.append(err)
        return missing

    # ================================================================
    # Derived fields computation
    # ================================================================

    def compute_derived_fields(self, conn: ConnectionRecord) -> None:
        """Compute display_string, combined_search, reference_id_bracket."""
        # combined_search = sender + receiver (no separator)
        conn.combined_search = f"{conn.sender_cid}{conn.receiver_cid}"

        # reference_id_bracket = "[Author, YYYY]"
        if conn.reference_id:
            conn.reference_id_bracket = f"[{conn.reference_id}]"

        # display_string = "rCID (00/00) [Ref1][Ref2];"
        if conn.receiver_cid and conn.reference_id:
            conn.display_string = (
                f"{conn.receiver_cid} (00/00) [{conn.reference_id}];"
            )

        # doc_link from reference
        if conn.reference_id in self.references:
            ref = self.references[conn.reference_id]
            if ref.doc:
                conn.doc_link = ref.doc
            if ref.journal:
                conn.journal_name = ref.journal

    # ================================================================
    # Literature type score
    # ================================================================

    @staticmethod
    def compute_literature_type_score(literature_type: str) -> float:
        """
        Score based on literature type.
        Mapping from existing data patterns:
          Experimental results → 1.0
          Review              → 0.8
          Data description    → 0.6
          Textbook            → 0.5
          Hypothesis          → 0.3
          Insight             → 0.2
          #Error              → 0.0
        """
        lt = literature_type.strip().lower() if literature_type else ""
        mapping = {
            "experimental results": 1.0,
            "review": 0.8,
            "data description": 0.6,
            "textbook": 0.5,
            "hypothesis": 0.3,
            "insight": 0.2,
        }
        for key, score in mapping.items():
            if key in lt:
                return score
        if "#error" in lt or not lt:
            return 0.0
        return 0.5  # default for unrecognized

    # ================================================================
    # Main conversion pipeline
    # ================================================================

    def convert(self, skip_credibility: bool = False) -> list[ConnectionRecord]:
        """
        Run the full conversion pipeline:
        1. Cross-validate references
        2. Compute derived fields
        3. Compute literature type scores
        4. Calculate PDER, CSI, and CR
        Returns the processed connection records.
        """
        # Step 1: Cross-validate
        self.cross_validate()

        for conn in self.connections:
            # Step 2: Derived fields
            self.compute_derived_fields(conn)

            # Step 3: Literature type score
            if conn.literature_type_score == 0.0 and conn.literature_type:
                conn.literature_type_score = self.compute_literature_type_score(
                    conn.literature_type
                )

            # Step 4: Credibility calculation
            if not skip_credibility:
                # PDER
                if conn.method_score_pder == 0.0 and conn.measurement_method:
                    conn.method_score_pder = self.credibility_calc.score_pder(
                        conn.measurement_method, conn.literature_type
                    )

                # CSI
                if conn.citation_sentiment_index == 0.0 and conn.reference_id:
                    doi = ""
                    if conn.reference_id in self.references:
                        doi = self.references[conn.reference_id].doi
                    conn.citation_sentiment_index = self.credibility_calc.score_csi(
                        conn.reference_id, doi
                    )

                # CR = product of all 6 scores
                conn.credibility_rating = self.credibility_calc.compute_cr(
                    source_region=conn.source_region_score,
                    receiver_region=conn.receiver_region_score,
                    csi=conn.citation_sentiment_index,
                    literature_type=conn.literature_type_score,
                    taxon=conn.taxon_score,
                    pder=conn.method_score_pder,
                )

                # Copy CR to summarized_cr as default
                conn.summarized_cr = conn.credibility_rating

        return self.connections

    # ================================================================
    # Output
    # ================================================================

    def write_bdbra_csv(self, output_path: str) -> int:
        """Write BDBRA CSV. Returns number of rows written."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(WB_CONNECTIONS_COLUMNS)
            for conn in self.connections:
                writer.writerow(conn.to_row())

        logger.info(f"Wrote {len(self.connections)} rows to {output_path}")
        return len(self.connections)

    def get_report(self) -> dict:
        """Generate a conversion report."""
        return {
            "references_loaded": len(self.references),
            "connections_loaded": len(self.connections),
            "errors": [repr(e) for e in self.errors],
            "warnings": [repr(w) for w in self.warnings],
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
        }


# ================================================================
# CLI entry point
# ================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Convert manual design data to BDBRA CSV"
    )
    parser.add_argument("-c", "--connections", required=True,
                        help="Input wbConnections CSV (new rows)")
    parser.add_argument("-r", "--references", required=True,
                        help="Input wbReferences CSV (new rows)")
    parser.add_argument("-o", "--output", required=True,
                        help="Output BDBRA CSV path")
    parser.add_argument("--contributor", default="",
                        help="Default contributor name")
    parser.add_argument("--project-id", default="",
                        help="Default project ID")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip credibility API calls, use heuristics")
    parser.add_argument("--report", default=None,
                        help="Save JSON report to this path")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # Initialize
    calc = CredibilityCalculator(use_api=not args.dry_run)
    converter = ManualToBdbraConverter(
        credibility_calc=calc,
        contributor=args.contributor,
        project_id=args.project_id,
    )

    # Load
    print(f"Loading references from: {args.references}")
    converter.load_references(args.references)

    print(f"Loading connections from: {args.connections}")
    converter.load_connections(args.connections)

    # Check for blocking errors
    if converter.errors:
        print(f"\n{'='*60}")
        print(f"VALIDATION ERRORS ({len(converter.errors)}):")
        for e in converter.errors:
            print(f"  {e}")
        print(f"{'='*60}")
        sys.exit(1)

    # Convert
    print(f"\nConverting {len(converter.connections)} connections...")
    converter.convert(skip_credibility=args.dry_run)

    # Output
    rows = converter.write_bdbra_csv(args.output)
    print(f"\nOutput: {args.output} ({rows} rows)")

    # Warnings
    if converter.warnings:
        print(f"\nWarnings ({len(converter.warnings)}):")
        for w in converter.warnings[:20]:
            print(f"  {w}")
        if len(converter.warnings) > 20:
            print(f"  ... and {len(converter.warnings)-20} more")

    # Report
    if args.report:
        report = converter.get_report()
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"Report saved: {args.report}")


if __name__ == "__main__":
    main()
