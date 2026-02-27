"""
pipeline.py — WholeBIF-RDB Data Ingestion Pipeline Orchestrator
================================================================

This module provides the top-level orchestration for the entire data
ingestion pipeline. It coordinates the following end-to-end flow:

  1. Initialize the CredibilityCalculator (heuristic or API mode)
  2. Initialize the ManualToBdbraConverter with default contributor/project
  3. Load wbReferences CSV into the converter
  4. Load wbConnections CSV into the converter
  5. Check for blocking validation errors (abort if any)
  6. Run the converter (derived fields + credibility scoring)
  7. Write the enriched BDBRA CSV output
  8. (Optional) Import into PostgreSQL via import_bdbra_into_wholebif.py
  9. Save a JSON execution report

The pipeline is designed to be:
  - Fault-tolerant: Errors are captured in the PipelineResult rather than
    crashing the process. This is important for batch/scheduled execution.
  - Observable: Execution time, record counts, errors, and warnings are
    all recorded in the JSON report.
  - Idempotent: Running the pipeline twice on the same input produces the
    same output (assuming deterministic scoring mode).

Usage:
    python pipeline.py \\
        --connections new_connections.csv \\
        --references new_references.csv \\
        --output-dir ./output \\
        --contributor "YutaName" \\
        --project-id "PROJECT01" \\
        [--dry-run] \\
        [--skip-import]
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from manual_to_bdbra_converter import ManualToBdbraConverter
from credibility_calculator import CredibilityCalculator

logger = logging.getLogger(__name__)


class PipelineResult:
    """
    Captures the outcome of a single pipeline execution.

    This object accumulates metrics, errors, and output paths throughout
    the pipeline run. It is returned by run_pipeline() and can be serialized
    to JSON for reporting.

    Design decision:
        We use a mutable result object rather than exceptions because the
        pipeline should always return a result (even on failure). This lets
        the caller inspect what happened without try/except, and enables
        batch scripts to log failures and continue with the next dataset.

    Attributes:
        success:            True if the pipeline completed without blocking errors.
        start_time:         Timestamp when the pipeline started.
        end_time:           Timestamp when the pipeline finished (set by finalize()).
        references_loaded:  Number of references loaded from CSV.
        connections_loaded: Number of connections loaded from CSV.
        connections_output: Number of rows written to the output BDBRA CSV.
        errors:             List of error message strings.
        warnings:           List of warning message strings.
        bdbra_csv_path:     Path to the generated BDBRA CSV (None if failed).
        report_path:        Path to the generated JSON report (None if failed).
    """
    def __init__(self):
        self.success = False
        self.start_time = datetime.now()
        self.end_time = None
        self.references_loaded = 0
        self.connections_loaded = 0
        self.connections_output = 0
        self.errors = []
        self.warnings = []
        self.bdbra_csv_path = None
        self.report_path = None

    def finalize(self):
        """Record the end time. Called in the finally block of run_pipeline()."""
        self.end_time = datetime.now()

    @property
    def duration_seconds(self) -> float:
        """Elapsed wall-clock time in seconds. Returns 0.0 if not finalized."""
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0

    def to_dict(self) -> dict:
        """
        Serialize to a JSON-friendly dict for report generation.

        Errors and warnings are capped at 50 entries to prevent
        excessively large report files when processing malformed data.
        """
        return {
            "success": self.success,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "references_loaded": self.references_loaded,
            "connections_loaded": self.connections_loaded,
            "connections_output": self.connections_output,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": self.errors[:50],
            "warnings": self.warnings[:50],
            "bdbra_csv_path": self.bdbra_csv_path,
        }


def run_pipeline(
    connections_csv: str,
    references_csv: str,
    output_dir: str,
    contributor: str = "",
    project_id: str = "",
    dry_run: bool = True,
    skip_import: bool = True,
) -> PipelineResult:
    """
    Execute the full data ingestion pipeline from CSV input to BDBRA output.

    This function is the primary programmatic entry point. It wraps the
    entire execution in a try/except/finally to ensure a PipelineResult
    is always returned, even if an unexpected error occurs.

    Args:
        connections_csv: Path to the input wbConnections CSV file.
        references_csv:  Path to the input wbReferences CSV file.
        output_dir:      Directory where output files will be written.
                        Created if it does not exist.
        contributor:     Default contributor name for records with empty fields.
        project_id:      Default project ID for records with empty fields.
        dry_run:         If True, use heuristic scoring only (no API calls).
                        If False, use Claude API for PDER and Semantic Scholar
                        for CSI (requires ANTHROPIC_API_KEY env var).
        skip_import:     If True, skip the PostgreSQL import step.
                        Currently always True as the import tool integration
                        is not yet complete.

    Returns:
        A PipelineResult object containing execution metrics, output paths,
        and any errors/warnings encountered.
    """
    result = PipelineResult()

    try:
        # ---- Prepare output directory ----
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Generate timestamped filenames to avoid overwriting previous runs
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        bdbra_filename = f"bdbra_{timestamp}.csv"
        bdbra_path = output_path / bdbra_filename

        # ---- Step 1: Initialize the credibility calculator ----
        # In dry-run mode, the calculator uses rule-based heuristics.
        # In production mode, it uses the Claude API and Semantic Scholar API.
        logger.info("Step 1: Initializing credibility calculator...")
        calc = CredibilityCalculator(use_api=not dry_run)

        # ---- Step 2: Initialize the converter ----
        logger.info("Step 2: Initializing converter...")
        converter = ManualToBdbraConverter(
            credibility_calc=calc,
            contributor=contributor,
            project_id=project_id,
        )

        # ---- Step 3: Load references ----
        # Must be loaded before connections so that cross-validation
        # and journal_name lookup can work.
        logger.info("Step 3: Loading references...")
        result.references_loaded = converter.load_references(references_csv)

        # ---- Step 4: Load connections ----
        logger.info("Step 4: Loading connections...")
        result.connections_loaded = converter.load_connections(connections_csv)

        # ---- Step 5: Check for blocking validation errors ----
        # Blocking errors (e.g., missing required fields) prevent the pipeline
        # from producing reliable output. We abort early and report the errors.
        if converter.errors:
            result.errors = [repr(e) for e in converter.errors]
            logger.error(f"Blocking validation errors: {len(converter.errors)}")
            result.finalize()
            return result

        # ---- Step 6: Run the conversion (derived fields + scoring) ----
        logger.info("Step 6: Converting and computing credibility...")
        converter.convert(skip_credibility=dry_run)

        # ---- Step 7: Write the BDBRA CSV output ----
        logger.info("Step 7: Writing BDBRA CSV...")
        result.connections_output = converter.write_bdbra_csv(str(bdbra_path))
        result.bdbra_csv_path = str(bdbra_path)

        # ---- Step 8: (Optional) Import to PostgreSQL ----
        # This step would invoke import_bdbra_into_wholebif.py to load the
        # BDBRA CSV into the production database. Currently disabled because
        # the import tool requires a live database connection.
        if not skip_import:
            logger.info("Step 8: Importing to PostgreSQL...")
            logger.warning("PostgreSQL import not yet integrated")

        # ---- Collect warnings for the report ----
        result.warnings = [repr(w) for w in converter.warnings]

        # ---- Save the JSON execution report ----
        report_path = output_path / f"report_{timestamp}.json"
        report = converter.get_report()
        report["pipeline_result"] = result.to_dict()
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        result.report_path = str(report_path)

        # Mark the pipeline as successful
        result.success = True
        logger.info(f"Pipeline completed successfully: {result.connections_output} rows")

    except Exception as e:
        # Catch any unexpected error and record it in the result.
        # The pipeline does NOT re-raise the exception — it returns a
        # result with success=False so the caller can handle it gracefully.
        logger.exception(f"Pipeline failed: {e}")
        result.errors.append(str(e))

    finally:
        # Always record the end time, regardless of success or failure.
        result.finalize()

    return result


# ========================================================================
# CLI Entry Point
# ========================================================================

def main():
    """
    Command-line interface for running the full pipeline.

    Parses arguments, runs the pipeline, and prints a summary to stdout.
    Exit code is 0 on success, 1 on failure.
    """
    parser = argparse.ArgumentParser(description="WholeBIF-RDB Ingestion Pipeline")
    parser.add_argument("-c", "--connections", required=True,
                        help="Path to input wbConnections CSV")
    parser.add_argument("-r", "--references", required=True,
                        help="Path to input wbReferences CSV")
    parser.add_argument("-o", "--output-dir", default="./output",
                        help="Output directory for BDBRA CSV and reports")
    parser.add_argument("--contributor", default="",
                        help="Default contributor name")
    parser.add_argument("--project-id", default="",
                        help="Default project ID")
    parser.add_argument("--dry-run", action="store_true",
                        help="Use heuristic scoring only (no API calls)")
    parser.add_argument("--skip-import", action="store_true", default=True,
                        help="Skip PostgreSQL import step")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable debug-level logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Execute the pipeline
    result = run_pipeline(
        connections_csv=args.connections,
        references_csv=args.references,
        output_dir=args.output_dir,
        contributor=args.contributor,
        project_id=args.project_id,
        dry_run=args.dry_run,
        skip_import=args.skip_import,
    )

    # Print a human-readable summary
    print(f"\n{'='*60}")
    print(f"Pipeline Result: {'SUCCESS' if result.success else 'FAILED'}")
    print(f"{'='*60}")
    print(f"  Duration: {result.duration_seconds:.1f}s")
    print(f"  References: {result.references_loaded}")
    print(f"  Connections in: {result.connections_loaded}")
    print(f"  Connections out: {result.connections_output}")
    print(f"  Errors: {len(result.errors)}")
    print(f"  Warnings: {len(result.warnings)}")
    if result.bdbra_csv_path:
        print(f"  Output: {result.bdbra_csv_path}")
    print(f"{'='*60}")

    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
