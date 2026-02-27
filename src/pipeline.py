"""
pipeline.py
===============
WholeBIF-RDB データ取り込みパイプライン全体のオーケストレーター。

フロー:
  1. Google Spreadsheet → CSV エクスポート（手動 or API）
  2. manual_to_bdbra_converter.py → BDBRA CSV 生成
  3. 信頼度計算 (PDER, CSI, CR)
  4. import_bdbra_into_wholebif.py → PostgreSQL 取り込み（既存ツール）

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
    """Pipeline execution result."""
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
        self.end_time = datetime.now()

    @property
    def duration_seconds(self) -> float:
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0

    def to_dict(self) -> dict:
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
    Execute the full data ingestion pipeline.

    Args:
        connections_csv: Path to new wbConnections CSV
        references_csv: Path to new wbReferences CSV
        output_dir: Directory for output files
        contributor: Default contributor name
        project_id: Default project ID
        dry_run: If True, use heuristic scoring (no API)
        skip_import: If True, skip PostgreSQL import step

    Returns:
        PipelineResult with execution details
    """
    result = PipelineResult()

    try:
        # Setup output directory
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        bdbra_filename = f"bdbra_{timestamp}.csv"
        bdbra_path = output_path / bdbra_filename

        # ---- Step 1: Initialize calculator ----
        logger.info("Step 1: Initializing credibility calculator...")
        calc = CredibilityCalculator(use_api=not dry_run)

        # ---- Step 2: Initialize converter ----
        logger.info("Step 2: Initializing converter...")
        converter = ManualToBdbraConverter(
            credibility_calc=calc,
            contributor=contributor,
            project_id=project_id,
        )

        # ---- Step 3: Load references ----
        logger.info("Step 3: Loading references...")
        result.references_loaded = converter.load_references(references_csv)

        # ---- Step 4: Load connections ----
        logger.info("Step 4: Loading connections...")
        result.connections_loaded = converter.load_connections(connections_csv)

        # ---- Step 5: Check for blocking errors ----
        if converter.errors:
            result.errors = [repr(e) for e in converter.errors]
            logger.error(f"Blocking validation errors: {len(converter.errors)}")
            result.finalize()
            return result

        # ---- Step 6: Convert (with credibility calculation) ----
        logger.info("Step 6: Converting and computing credibility...")
        converter.convert(skip_credibility=dry_run)

        # ---- Step 7: Write BDBRA CSV ----
        logger.info("Step 7: Writing BDBRA CSV...")
        result.connections_output = converter.write_bdbra_csv(str(bdbra_path))
        result.bdbra_csv_path = str(bdbra_path)

        # ---- Step 8: (Optional) Import to PostgreSQL ----
        if not skip_import:
            logger.info("Step 8: Importing to PostgreSQL...")
            # This would call import_bdbra_into_wholebif.py
            # For now, we skip it as it requires DB connection
            logger.warning("PostgreSQL import not yet integrated")

        # ---- Collect warnings ----
        result.warnings = [repr(w) for w in converter.warnings]

        # ---- Save report ----
        report_path = output_path / f"report_{timestamp}.json"
        report = converter.get_report()
        report["pipeline_result"] = result.to_dict()
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        result.report_path = str(report_path)

        result.success = True
        logger.info(f"Pipeline completed successfully: {result.connections_output} rows")

    except Exception as e:
        logger.exception(f"Pipeline failed: {e}")
        result.errors.append(str(e))

    finally:
        result.finalize()

    return result


def main():
    parser = argparse.ArgumentParser(description="WholeBIF-RDB Ingestion Pipeline")
    parser.add_argument("-c", "--connections", required=True)
    parser.add_argument("-r", "--references", required=True)
    parser.add_argument("-o", "--output-dir", default="./output")
    parser.add_argument("--contributor", default="")
    parser.add_argument("--project-id", default="")
    parser.add_argument("--dry-run", action="store_true",
                        help="Use heuristic scoring (no API calls)")
    parser.add_argument("--skip-import", action="store_true", default=True,
                        help="Skip PostgreSQL import step")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    result = run_pipeline(
        connections_csv=args.connections,
        references_csv=args.references,
        output_dir=args.output_dir,
        contributor=args.contributor,
        project_id=args.project_id,
        dry_run=args.dry_run,
        skip_import=args.skip_import,
    )

    # Print summary
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
