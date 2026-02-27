"""
manual_to_bdbra_converter.py — CSV Conversion and Enrichment Pipeline
======================================================================

This module is the core data transformation engine of the WholeBIF-RDB
pipeline. It corresponds to the red-boxed "manual_to_bdbra_converter.py"
component in the pipeline architecture diagram.

What it does:
  Takes raw CSV exports from Google Spreadsheet (wbConnections + wbReferences),
  validates them, enriches them with computed fields and credibility scores,
  and outputs a BDBRA CSV that is ready for import into PostgreSQL via
  the existing import_bdbra_into_wholebif.py tool.

Processing steps (in order):
  1. Load wbReferences CSV → ReferenceRecord objects
  2. Load wbConnections CSV → ConnectionRecord objects
  3. Cross-validate: ensure every Connection's Reference ID exists in References
  4. Compute derived fields (display_string, combined_search, etc.)
  5. Compute Literature Type Score from the literature type string
  6. Calculate PDER and CSI via CredibilityCalculator
  7. Calculate CR = product of all 6 scores
  8. Write the enriched records to BDBRA CSV

Input:
  - wbConnections CSV exported from Google Spreadsheet (new rows to ingest)
  - wbReferences CSV exported from Google Spreadsheet (corresponding refs)

Output:
  - BDBRA CSV (42-column format, all scores populated)
  - JSON conversion report (counts, errors, warnings)

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
    """Raised when the conversion process encounters an unrecoverable error."""
    pass


class ManualToBdbraConverter:
    """
    Converts manually curated neuroscience data from Google Spreadsheet
    exports into the BDBRA CSV format used by the WholeBIF-RDB database.

    This class manages the full lifecycle of a conversion:
      - Loading and validating input CSVs
      - Cross-referencing connections against the reference table
      - Computing derived display/search fields
      - Orchestrating credibility score calculations
      - Writing the final output CSV and reports

    Attributes:
        credibility_calc: The CredibilityCalculator instance used for
                         PDER, CSI, and CR computation.
        contributor:     Default contributor name applied to records that
                        have an empty Contributor field (common in Spreadsheet
                        exports where this column is left blank).
        project_id:     Default project ID, applied similarly.
        references:     Dict mapping Reference ID → ReferenceRecord.
        connections:    List of ConnectionRecord objects loaded from CSV.
        errors:         Validation errors (severity="error") that block output.
        warnings:       Validation warnings (severity="warning") that are
                       logged but do not block output.
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

    # ====================================================================
    # Step 1 & 2: Loading CSV Data
    # ====================================================================

    def load_references(self, csv_path: str) -> int:
        """
        Load reference records from a wbReferences CSV file.

        Each row is parsed into a ReferenceRecord and validated.
        Valid records are stored in self.references keyed by reference_id.
        Validation errors/warnings are accumulated in self.errors/self.warnings.

        Args:
            csv_path: Path to the wbReferences CSV file.

        Returns:
            The number of reference records successfully loaded.

        Raises:
            FileNotFoundError: If the CSV file does not exist. This is raised
                              immediately (not accumulated as an error) because
                              the pipeline cannot proceed without references.
        """
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"References CSV not found: {csv_path}")

        count = 0
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader)  # Skip the header row

            for row_num, row in enumerate(reader, start=2):
                # Skip completely empty rows (common at the end of Spreadsheet exports)
                if not any(cell.strip() for cell in row):
                    continue

                ref = ReferenceRecord.from_row(row)

                # Validate and categorize any issues
                errs = validate_reference(ref)
                for e in errs:
                    # Prefix error messages with the row number for easy debugging
                    e.message = f"Row {row_num}: {e.message}"
                    if e.severity == "error":
                        self.errors.append(e)
                    else:
                        self.warnings.append(e)

                # Index by reference_id (the join key with wbConnections)
                if ref.reference_id:
                    self.references[ref.reference_id] = ref
                    count += 1

        logger.info(f"Loaded {count} references from {csv_path}")
        return count

    def load_connections(self, csv_path: str) -> int:
        """
        Load connection records from a wbConnections CSV file.

        Each row is parsed into a ConnectionRecord, padded to 42 columns
        if necessary (Spreadsheet exports often drop trailing empty columns),
        and validated. Default contributor/project_id values are applied to
        records with empty administrative fields.

        Args:
            csv_path: Path to the wbConnections CSV file.

        Returns:
            The number of connection records loaded.

        Raises:
            FileNotFoundError: If the CSV file does not exist.
        """
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"Connections CSV not found: {csv_path}")

        count = 0
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader)  # Skip the header row

            for row_num, row in enumerate(reader, start=2):
                # Skip completely empty rows
                if not any(cell.strip() for cell in row):
                    continue

                # Pad short rows to the expected 42-column width.
                # Google Spreadsheet drops trailing empty columns on export,
                # so a row with data only in columns 0-15 may arrive as a
                # 16-element list instead of 42.
                while len(row) < len(WB_CONNECTIONS_COLUMNS):
                    row.append("")

                conn = ConnectionRecord.from_row(row)

                # Apply default contributor and project_id to empty fields.
                # This is a common scenario: the Spreadsheet template has these
                # columns but contributors rarely fill them in per-row.
                if not conn.contributor and self.contributor:
                    conn.contributor = self.contributor
                if not conn.project_id and self.project_id:
                    conn.project_id = self.project_id

                # Validate and categorize issues
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

    # ====================================================================
    # Step 3: Cross-Reference Validation
    # ====================================================================

    def cross_validate(self) -> list[ValidationError]:
        """
        Verify that every connection's Reference ID exists in the reference table.

        This is critical because:
          - If a reference is missing, the CSI calculation will fall back to
            the year-based heuristic instead of using cached or API-derived
            scores, potentially misrepresenting the paper's citation quality.
          - The journal_name derived field depends on looking up the reference.

        Known placeholder values ("author, year", "#N/A", "") are exempted
        from this check since they represent data entry errors, not missing
        references.

        Returns:
            A list of ValidationError objects for missing references.
            These are also appended to self.warnings.
        """
        missing = []
        for i, conn in enumerate(self.connections):
            ref_id = conn.reference_id
            if ref_id and ref_id not in self.references:
                # Skip known placeholder/error values
                if ref_id not in ("author, year", "#N/A", ""):
                    err = ValidationError(
                        "reference_id",
                        f"Connection #{i+1}: Reference '{ref_id}' not found in wbReferences",
                        severity="warning",
                    )
                    self.warnings.append(err)
                    missing.append(err)
        return missing

    # ====================================================================
    # Step 4: Derived Fields Computation
    # ====================================================================

    def compute_derived_fields(self, conn: ConnectionRecord) -> None:
        """
        Populate auto-generated fields that are required in the BDBRA CSV
        but are not present in the raw Spreadsheet export.

        Fields computed:
          - combined_search: Concatenation of sender_cid and receiver_cid
            (e.g., "CA1" + "Sub" = "CA1Sub"). Used as a search index key
            in the WholeBIF-RDB query interface.

          - reference_id_bracket: The reference ID wrapped in square brackets
            (e.g., "[Amaral, 1991]"). Used in display strings.

          - display_string: A formatted string for the UI that shows the
            receiver region, placeholder date, and reference in brackets.
            Format: "rCID (00/00) [Reference ID];"

          - journal_name: Looked up from the reference table using the
            connection's reference_id. Populates the "Journal names" column.

          - doc_link: Document URL copied from the reference record.

        Args:
            conn: A ConnectionRecord to enrich. Modified in place.
        """
        # Search index: concatenation of sender and receiver CIDs
        conn.combined_search = f"{conn.sender_cid}{conn.receiver_cid}"

        # Bracket-wrapped reference ID for display purposes
        if conn.reference_id:
            conn.reference_id_bracket = f"[{conn.reference_id}]"

        # Full display string for the join-view UI
        if conn.receiver_cid and conn.reference_id:
            conn.display_string = (
                f"{conn.receiver_cid} (00/00) [{conn.reference_id}];"
            )

        # Look up reference metadata (journal name, document link)
        if conn.reference_id in self.references:
            ref = self.references[conn.reference_id]
            if ref.doc:
                conn.doc_link = ref.doc
            if ref.journal:
                conn.journal_name = ref.journal

    # ====================================================================
    # Step 5: Literature Type Score
    # ====================================================================

    @staticmethod
    def compute_literature_type_score(literature_type: str) -> float:
        """
        Map a literature type string to a numeric score.

        The scores reflect how directly the literature type provides
        evidence for neural connectivity:

          - Experimental results (1.0): Original data from the authors' own
            experiments. The most reliable type of evidence.
          - Review (0.8): Synthesis of multiple studies. Still valuable but
            secondhand.
          - Data description (0.6): Observational account without full
            experimental methodology.
          - Textbook (0.5): Educational material, potentially oversimplified.
          - Hypothesis (0.3): Unverified theoretical proposal.
          - Insight (0.2): Perspective or commentary piece.
          - Error / empty (0.0): Data entry errors or missing values.

        Matching is case-insensitive and uses substring containment, so
        "experimental results" matches both "Experimental results" and
        "EXPERIMENTAL RESULTS". This is important because Google Spreadsheet
        hand-entry produces inconsistent capitalization.

        Args:
            literature_type: The literature type string from the record.

        Returns:
            A float score in [0.0, 1.0].
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

        # Handle error values and empty strings
        if "#error" in lt or not lt:
            return 0.0

        # Unrecognized literature types get a middle-ground default
        return 0.5

    # ====================================================================
    # Step 6-7: Main Conversion Pipeline
    # ====================================================================

    def convert(self, skip_credibility: bool = False) -> list[ConnectionRecord]:
        """
        Execute the full conversion pipeline on all loaded connections.

        This method runs steps 3-7 of the processing flow:
          3. Cross-validate references
          4. Compute derived fields (display_string, combined_search, etc.)
          5. Compute Literature Type Score
          6. Calculate PDER and CSI (unless skip_credibility=True)
          7. Calculate CR as the product of all 6 scores

        Args:
            skip_credibility: If True, skip PDER/CSI/CR calculation.
                             Useful for dry-run mode where only derived
                             field generation is needed.

        Returns:
            The list of processed ConnectionRecord objects (same objects
            as self.connections, modified in place).
        """
        # Step 3: Cross-validate reference integrity
        self.cross_validate()

        for conn in self.connections:
            # Step 4: Generate display/search fields
            self.compute_derived_fields(conn)

            # Step 5: Compute Literature Type Score (only if not already set)
            # The "== 0.0" check avoids overwriting scores that were already
            # present in the input CSV (e.g., from a previous processing run).
            if conn.literature_type_score == 0.0 and conn.literature_type:
                conn.literature_type_score = self.compute_literature_type_score(
                    conn.literature_type
                )

            # Steps 6-7: Credibility scoring
            if not skip_credibility:
                # PDER: only compute if not already set and method is available
                if conn.method_score_pder == 0.0 and conn.measurement_method:
                    conn.method_score_pder = self.credibility_calc.score_pder(
                        conn.measurement_method, conn.literature_type
                    )

                # CSI: only compute if not already set and reference is available
                if conn.citation_sentiment_index == 0.0 and conn.reference_id:
                    doi = ""
                    if conn.reference_id in self.references:
                        doi = self.references[conn.reference_id].doi
                    conn.citation_sentiment_index = self.credibility_calc.score_csi(
                        conn.reference_id, doi
                    )

                # CR: always recompute from the current component scores.
                # This ensures consistency even if individual scores were
                # loaded from the input CSV.
                conn.credibility_rating = self.credibility_calc.compute_cr(
                    source_region=conn.source_region_score,
                    receiver_region=conn.receiver_region_score,
                    csi=conn.citation_sentiment_index,
                    literature_type=conn.literature_type_score,
                    taxon=conn.taxon_score,
                    pder=conn.method_score_pder,
                )

                # Initialize summarized_cr to match CR.
                # This will be overwritten later if multiple records exist
                # for the same sender→receiver projection.
                conn.summarized_cr = conn.credibility_rating

        return self.connections

    # ====================================================================
    # Step 8: Output
    # ====================================================================

    def write_bdbra_csv(self, output_path: str) -> int:
        """
        Write all connection records to a BDBRA CSV file.

        The output CSV has exactly 42 columns matching the wbConnections schema
        (WB_CONNECTIONS_COLUMNS). The header row is written first, followed by
        one row per ConnectionRecord.

        The output directory is created if it does not exist.

        Args:
            output_path: Path for the output CSV file.

        Returns:
            The number of data rows written (excluding the header).
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            # Write the 42-column header
            writer.writerow(WB_CONNECTIONS_COLUMNS)
            # Write each connection as a row
            for conn in self.connections:
                writer.writerow(conn.to_row())

        logger.info(f"Wrote {len(self.connections)} rows to {output_path}")
        return len(self.connections)

    def get_report(self) -> dict:
        """
        Generate a summary report of the conversion process.

        Returns:
            A dict containing:
              - references_loaded: Number of references in the reference table
              - connections_loaded: Number of connection records processed
              - errors: List of error descriptions (blocking issues)
              - warnings: List of warning descriptions (non-blocking issues)
              - error_count / warning_count: Counts for quick assessment
        """
        return {
            "references_loaded": len(self.references),
            "connections_loaded": len(self.connections),
            "errors": [repr(e) for e in self.errors],
            "warnings": [repr(w) for w in self.warnings],
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
        }


# ========================================================================
# CLI Entry Point
# ========================================================================

def main():
    """
    Command-line interface for running the converter standalone.

    This is primarily used for manual/debugging runs. In production,
    the pipeline.py orchestrator calls the converter programmatically.
    """
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
                        help="Default contributor name for empty Contributor fields")
    parser.add_argument("--project-id", default="",
                        help="Default project ID for empty Project ID fields")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip credibility API calls; use heuristics only")
    parser.add_argument("--report", default=None,
                        help="Save JSON conversion report to this path")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # Initialize the calculator and converter
    calc = CredibilityCalculator(use_api=not args.dry_run)
    converter = ManualToBdbraConverter(
        credibility_calc=calc,
        contributor=args.contributor,
        project_id=args.project_id,
    )

    # Load input data
    print(f"Loading references from: {args.references}")
    converter.load_references(args.references)

    print(f"Loading connections from: {args.connections}")
    converter.load_connections(args.connections)

    # Abort if there are blocking validation errors
    if converter.errors:
        print(f"\n{'='*60}")
        print(f"VALIDATION ERRORS ({len(converter.errors)}):")
        for e in converter.errors:
            print(f"  {e}")
        print(f"{'='*60}")
        sys.exit(1)

    # Run the conversion pipeline
    print(f"\nConverting {len(converter.connections)} connections...")
    converter.convert(skip_credibility=args.dry_run)

    # Write output
    rows = converter.write_bdbra_csv(args.output)
    print(f"\nOutput: {args.output} ({rows} rows)")

    # Report warnings
    if converter.warnings:
        print(f"\nWarnings ({len(converter.warnings)}):")
        for w in converter.warnings[:20]:  # Show first 20 to avoid flooding terminal
            print(f"  {w}")
        if len(converter.warnings) > 20:
            print(f"  ... and {len(converter.warnings)-20} more")

    # Save optional JSON report
    if args.report:
        report = converter.get_report()
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"Report saved: {args.report}")


if __name__ == "__main__":
    main()
