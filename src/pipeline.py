#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline.py
-----------
Run the full WholeBIF-RDB ingestion pipeline: out_gpt52.csv -> PostgreSQL.

Steps:
  1  enrich_dhba.py                                    sender/receiver -> dhbasid/dhbarid
  2  enrich_references.py                              PMID -> DOI / BibTeX
  3  score_records.py                                  journalscore / methodscore / citationscore
  4  compute_summarized_cr.py                          credibility_rating and summarized_cr
  5  import_bdbra_into_wholebif_v4_enhanced_patched.py PostgreSQL upsert

Intermediate CSV files are written to --work-dir (default: ./work/).
Use --start-step to resume from a specific step when intermediate files already exist.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent


def run(cmd: list[str], label: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print(f"[ERROR] {label} exited with code {result.returncode}", file=sys.stderr)
        sys.exit(result.returncode)


def _require(path: Path, step: int) -> None:
    if not path.exists():
        print(
            f"[ERROR] --start-step={step} requires {path}, but the file was not found.",
            file=sys.stderr,
        )
        sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="WholeBIF-RDB full pipeline: out_gpt52.csv -> PostgreSQL"
    )
    ap.add_argument("--input",        required=True, help="Input CSV (out_gpt52.csv format)")
    ap.add_argument("--regions",      required=True, help="Path to BrainRegions.csv")
    ap.add_argument("--work-dir",     default="./work",
                    help="Directory for intermediate CSV files (default: ./work)")
    ap.add_argument("--start-step",   type=int, default=1, choices=[1, 2, 3, 4, 5],
                    help="Step to start from (default: 1)")
    ap.add_argument("--skip-citation", action="store_true",
                    help="Skip citationscore in step 3 (no NCBI or Claude API calls)")
    ap.add_argument("--host",         default="localhost")
    ap.add_argument("--port",         default="5432")
    ap.add_argument("--dbname",       default="wholebif_rdb")
    ap.add_argument("--user",         default="wholebif")
    ap.add_argument("--password",     default="")
    ap.add_argument("--dry-run",      action="store_true",
                    help="Skip step 5 (database import)")
    ap.add_argument("--commit-every", type=int, default=500,
                    help="Commit interval for step 5 (default: 500)")

    args = ap.parse_args()

    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)

    step1_out = work / "step1_dhba.csv"
    step2_out = work / "step2_refs.csv"
    step3_out = work / "step3_scored.csv"
    step4_out = work / "step4_cr.csv"   # final CSV sent to the database

    py  = sys.executable
    src = HERE

    # -- Step 1: attach DHBA IDs -----------------------------------------
    if args.start_step <= 1:
        shutil.copy(args.input, step1_out)
        run([
            py, str(src / "enrich_dhba.py"),
            "--input",   str(step1_out),
            "--regions", args.regions,
        ], "Step 1: attach DHBA IDs (enrich_dhba.py)")
    else:
        _require(step1_out, args.start_step)

    # -- Step 2: fill DOI / BibTeX ---------------------------------------
    if args.start_step <= 2:
        shutil.copy(step1_out, step2_out)
        run([
            py, str(src / "enrich_references.py"),
            "--input", str(step2_out),
        ], "Step 2: fill DOI / BibTeX (enrich_references.py)")
    else:
        _require(step2_out, args.start_step)

    # -- Step 3: compute scores ------------------------------------------
    if args.start_step <= 3:
        shutil.copy(step2_out, step3_out)
        score_cmd = [py, str(src / "score_records.py"), "--input", str(step3_out)]
        if args.skip_citation:
            score_cmd.append("--skip-citation")
        run(score_cmd, "Step 3: compute scores (score_records.py)")
    else:
        _require(step3_out, args.start_step)

    # -- Step 4: compute summarized_cr (Bayesian) ------------------------
    if args.start_step <= 4:
        shutil.copy(step3_out, step4_out)
        run([
            py, str(src / "compute_summarized_cr.py"),
            "--input", str(step4_out),
        ], "Step 4: Bayesian summarized_cr (compute_summarized_cr.py)")
    else:
        _require(step4_out, args.start_step)

    # -- Step 5: import into PostgreSQL ----------------------------------
    if args.dry_run:
        print("\n[DRY RUN] Step 5 skipped.")
        print(f"  Final CSV: {step4_out}")
        return

    if args.start_step <= 5:
        run([
            py, str(src / "import_bdbra_into_wholebif_v4_enhanced_patched.py"),
            "--csv",          str(step4_out),
            "--host",         args.host,
            "--port",         str(args.port),
            "--dbname",       args.dbname,
            "--user",         args.user,
            "--password",     args.password,
            "--commit_every", str(args.commit_every),
        ], "Step 5: import into PostgreSQL (import_bdbra_into_wholebif_v4_enhanced_patched.py)")

    print("\n[pipeline] All steps completed.")
    print(f"  Final CSV: {step4_out}")


if __name__ == "__main__":
    main()
