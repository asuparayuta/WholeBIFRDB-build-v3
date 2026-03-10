#!/usr/bin/env python3
"""
pipeline.py
============
Neural Projection Directionality Scoring Pipeline — Orchestrator

Runs all three stages end-to-end:

  Stage 1: Summarise ~1100 papers
           Input  → data/papers_input.csv
           Output → data/stage1_summaries.jsonl

  Stage 2: Extract experimental methods per paper
           Input  → data/stage1_summaries.jsonl
           Output → data/stage2_methods.jsonl
                    data/stage2_method_index.json

  Stage 3: Score each method using the aggregated paper evidence
           Input  → data/stage2_method_index.json
           Output → data/stage3_scores.json

Usage:
    # Full run (all stages)
    python pipeline.py --api claude

    # Resume after an interruption
    python pipeline.py --api claude --resume

    # Run only a specific stage
    python pipeline.py --api claude --stages 2 3

    # Test with first 20 papers only
    python pipeline.py --api claude --limit 20

    # Use OpenAI instead
    python pipeline.py --api openai --model gpt-4.1
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


HERE = Path(__file__).parent
STAGES_DIR = HERE / "stages"
DATA_DIR   = HERE / "data"


# ---------------------------------------------------------------------------
# Stage definitions
# ---------------------------------------------------------------------------

STAGE_SCRIPTS = {
    1: STAGES_DIR / "stage1_summarize.py",
    2: STAGES_DIR / "stage2_extract_methods.py",
    3: STAGES_DIR / "stage3_score_methods.py",
}

STAGE_NAMES = {
    1: "Paper Summarization",
    2: "Method Extraction",
    3: "Evidence-Grounded Scoring",
}

STAGE_OUTPUTS = {
    1: DATA_DIR / "stage1_summaries.jsonl",
    2: DATA_DIR / "stage2_method_index.json",
    3: DATA_DIR / "stage3_scores.json",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def print_banner(stage: int) -> None:
    name = STAGE_NAMES[stage]
    bar  = "=" * 60
    print(f"\n{bar}")
    print(f"  STAGE {stage}: {name}")
    print(f"{bar}\n")


def check_input_file(path: Path, stage: int) -> None:
    if not path.exists():
        sys.exit(
            f"ERROR: Input for Stage {stage} not found:\n  {path}\n"
            f"Run Stage {stage - 1} first."
        )


def count_jsonl_lines(path: Path) -> int:
    if not path.exists():
        return 0
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                n += 1
    return n


def run_stage(
    stage_num: int,
    args: argparse.Namespace,
    extra_flags: list[str] | None = None,
) -> bool:
    """Run a single stage script as a subprocess. Returns True on success."""
    script = STAGE_SCRIPTS[stage_num]
    cmd = [sys.executable, str(script)]

    # Pass through common flags
    cmd += ["--api", args.api]
    if args.model:
        cmd += ["--model", args.model]
    if args.resume:
        cmd.append("--resume")
    if args.verbose:
        cmd.append("--verbose")

    # Stage-specific flags
    if stage_num in (1, 2) and args.limit:
        cmd += ["--limit", str(args.limit)]
    if stage_num == 3 and args.min_papers:
        cmd += ["--min-papers", str(args.min_papers)]

    if extra_flags:
        cmd += extra_flags

    print(f"Running: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, cwd=str(HERE))
    return result.returncode == 0


# ---------------------------------------------------------------------------
# Post-stage reporting
# ---------------------------------------------------------------------------

def report_stage1(output_path: Path) -> None:
    n = count_jsonl_lines(output_path)
    n_ok = n_err = 0
    if output_path.exists():
        with open(output_path, encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    if obj.get("_status") == "ok":
                        n_ok += 1
                    else:
                        n_err += 1
                except Exception:
                    pass
    print(f"\n[Stage 1 summary] {n_ok} OK / {n_err} errors  →  {output_path}")


def report_stage2(index_path: Path) -> None:
    if not index_path.exists():
        return
    with open(index_path, encoding="utf-8") as f:
        index = json.load(f)
    n_methods = len(index)
    n_papers  = sum(len(v) for v in index.values())
    n_human   = sum(
        sum(1 for e in v if e.get("applied_to_human"))
        for v in index.values()
    )
    print(f"\n[Stage 2 summary] {n_methods} unique methods  |  "
          f"{n_papers} total method-paper links  |  "
          f"{n_human} human-applicable records")
    print(f"  Top 5 methods by paper count:")
    for method, records in sorted(index.items(), key=lambda x: -len(x[1]))[:5]:
        print(f"    {method:<50}  {len(records):>4} papers")


def report_stage3(output_path: Path) -> None:
    if not output_path.exists():
        return
    with open(output_path, encoding="utf-8") as f:
        data = json.load(f)
    scored = data.get("scored_methods", [])
    print(f"\n[Stage 3 summary] {len(scored)} methods scored")
    print(f"\n  {'Method':<48} {'Score':>6}  {'Papers':>7}")
    print("  " + "-" * 64)
    for r in sorted(scored, key=lambda x: x.get("directionality_score") or 0, reverse=True):
        name  = r.get("method_name", "")[:46]
        score = r.get("directionality_score")
        n     = r.get("_n_papers", "?")
        s     = f"{score:.2f}" if score is not None else "  ERR"
        print(f"  {name:<48} {s:>6}  {n:>7}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Neural Projection Scoring Pipeline — Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full run with Claude
  python pipeline.py --api claude

  # Resume after interruption
  python pipeline.py --api claude --resume

  # Only stages 2 and 3 (Stage 1 already done)
  python pipeline.py --api claude --stages 2 3

  # Quick test: first 20 papers, no summary
  python pipeline.py --api claude --limit 20

  # OpenAI with specific model
  python pipeline.py --api openai --model gpt-4.1
        """,
    )
    p.add_argument("--api",        choices=["claude", "openai"], default="claude",
                   help="Which LLM API to use (default: claude)")
    p.add_argument("--model",      default=None,
                   help="Override default model (e.g. claude-opus-4-6 or gpt-4.1)")
    p.add_argument("--stages",     nargs="+", type=int, choices=[1, 2, 3],
                   default=[1, 2, 3], help="Which stages to run (default: 1 2 3)")
    p.add_argument("--resume",     action="store_true",
                   help="Skip already-processed records in stages 1 and 2")
    p.add_argument("--limit",      type=int, default=None,
                   help="Limit stages 1 and 2 to first N papers (for testing)")
    p.add_argument("--min-papers", type=int, default=None,
                   help="Stage 3: skip methods with fewer than N supporting papers")
    p.add_argument("--verbose",    action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Validate API key(s)
    if args.api == "claude" and not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ERROR: ANTHROPIC_API_KEY not set")
    if args.api == "openai" and not os.environ.get("OPENAI_API_KEY"):
        sys.exit("ERROR: OPENAI_API_KEY not set")

    start_time = time.time()
    print("=" * 60)
    print("  Neural Projection Directionality Scoring Pipeline")
    print(f"  API: {args.api.upper()}  |  Stages: {args.stages}")
    print("=" * 60)

    stages_to_run = sorted(args.stages)

    # ── Stage 1 ─────────────────────────────────────────────────────────
    if 1 in stages_to_run:
        # Verify input file exists
        input_csv = DATA_DIR / "papers_input.csv"
        if not input_csv.exists():
            sys.exit(
                f"ERROR: Input file not found: {input_csv}\n"
                "Please provide a CSV with columns: pubmed_id, title, abstract, fulltext\n"
                "See data/papers_input_example.csv for format."
            )
        print_banner(1)
        ok = run_stage(1, args)
        report_stage1(STAGE_OUTPUTS[1])
        if not ok:
            sys.exit("Stage 1 failed. Aborting pipeline.")

    # ── Stage 2 ─────────────────────────────────────────────────────────
    if 2 in stages_to_run:
        if 1 not in stages_to_run:  # user skipped Stage 1
            check_input_file(STAGE_OUTPUTS[1], 2)
        print_banner(2)
        ok = run_stage(2, args)
        report_stage2(STAGE_OUTPUTS[2])
        if not ok:
            sys.exit("Stage 2 failed. Aborting pipeline.")

    # ── Stage 3 ─────────────────────────────────────────────────────────
    if 3 in stages_to_run:
        if 2 not in stages_to_run:
            check_input_file(STAGE_OUTPUTS[2], 3)
        print_banner(3)
        ok = run_stage(3, args)
        report_stage3(STAGE_OUTPUTS[3])
        if not ok:
            sys.exit("Stage 3 failed.")

    elapsed = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"  Pipeline complete in {elapsed:.0f}s")
    print(f"  Final scores: {STAGE_OUTPUTS[3].resolve()}")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
