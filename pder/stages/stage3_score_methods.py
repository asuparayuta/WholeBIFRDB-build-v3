#!/usr/bin/env python3
"""
stage3_score_methods.py
========================
Stage 3 of the Neural Projection Scoring Pipeline.

Reads the Stage 2 method index (aggregated evidence per method) and
assigns evidence-grounded directionality scores to each method.

Input  : data/stage2_method_index.json
Output : data/stage3_scores.json   (final scores + WholeBIF-RDB weights)

Usage:
    python stage3_score_methods.py [--input FILE] [--output FILE]
                                   [--api claude|openai] [--model MODEL]
                                   [--min-papers N] [--verbose]
"""

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from prompts import (
    STAGE3_SYSTEM,
    STAGE3_USER_TEMPLATE,
    STAGE3_SUMMARY_SYSTEM,
    STAGE3_SUMMARY_USER_TEMPLATE,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_INPUT  = Path(__file__).parent.parent / "data" / "stage2_method_index.json"
DEFAULT_OUTPUT = Path(__file__).parent.parent / "data" / "stage3_scores.json"

CLAUDE_MODEL  = "claude-sonnet-4-6"
OPENAI_MODEL  = "gpt-4.1"
MAX_TOKENS    = 1200
TEMPERATURE   = 0.0
REQUEST_DELAY = 0.8

# Minimum number of papers to score a method individually.
# Methods with fewer papers are scored together in a batch with a lower-
# confidence flag rather than individually.
MIN_PAPERS_FOR_INDIVIDUAL_SCORE = 3


# ---------------------------------------------------------------------------
# LLM call wrappers
# ---------------------------------------------------------------------------

def call_claude(client, system: str, prompt_user: str, model: str) -> str:
    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        system=system,
        messages=[{"role": "user", "content": prompt_user}],
    )
    return response.content[0].text.strip()


def call_openai(client, system: str, prompt_user: str, model: str) -> str:
    response = client.chat.completions.create(
        model=model,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt_user},
        ],
    )
    return response.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# Evidence summarisation helpers
# ---------------------------------------------------------------------------

def summarise_evidence(evidence_list: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Compute aggregate statistics from all paper evidence for one method.
    These statistics are embedded in the Stage 3 prompt to ground the LLM.
    """
    n_total = len(evidence_list)
    n_human = sum(1 for e in evidence_list if e.get("applied_to_human"))

    direction_counts: Counter = Counter(
        e.get("directionality_type", "unclear") for e in evidence_list
    )
    confidence_counts: Counter = Counter(
        e.get("direction_confidence", "unclear") for e in evidence_list
    )
    n_high_conf = confidence_counts.get("high", 0)

    # Build direction breakdown string for the prompt
    direction_breakdown = "\n".join(
        f"  {dtype:<35} {count:>4} papers"
        for dtype, count in direction_counts.most_common()
    )

    # Select up to 10 most informative evidence records for the prompt.
    # Prioritise: human > high confidence > anterograde/retrograde defined.
    def evidence_priority(e: dict) -> tuple:
        return (
            int(e.get("applied_to_human", False)),
            {"high": 2, "medium": 1, "low": 0, "none": -1}.get(
                e.get("direction_confidence", ""), 0
            ),
            int(e.get("directionality_type", "") in
                ("anterograde_defined", "retrograde_defined", "functional_directed")),
        )

    top_evidence = sorted(evidence_list, key=evidence_priority, reverse=True)[:10]

    evidence_records_str = json.dumps(
        [
            {
                "pubmed_id":               e.get("pubmed_id"),
                "applied_to_human":        e.get("applied_to_human"),
                "directionality_type":     e.get("directionality_type"),
                "direction_confidence":    e.get("direction_confidence"),
                "how_determined":          e.get("how_direction_was_determined"),
                "source":                  e.get("source_region"),
                "target":                  e.get("target_region"),
                "evidence_sentence":       e.get("evidence_sentence"),
            }
            for e in top_evidence
        ],
        ensure_ascii=False,
        indent=2,
    )

    # Representative category (most common)
    categories = [e.get("method_category") for e in evidence_list if e.get("method_category")]
    most_common_category = Counter(categories).most_common(1)[0][0] if categories else "unknown"

    return {
        "n_papers":          n_total,
        "n_human":           n_human,
        "n_high_conf":       n_high_conf,
        "direction_breakdown": direction_breakdown,
        "evidence_records":  evidence_records_str,
        "method_category":   most_common_category,
    }


# ---------------------------------------------------------------------------
# Core scoring
# ---------------------------------------------------------------------------

def score_one_method(
    method_name: str,
    evidence_list: list[dict[str, Any]],
    call_fn,
    model: str,
    verbose: bool = False,
) -> dict[str, Any]:
    """Score a single method given its aggregated evidence."""

    stats = summarise_evidence(evidence_list)

    prompt = STAGE3_USER_TEMPLATE.format(
        method_name=method_name,
        method_category=stats["method_category"],
        n_papers=stats["n_papers"],
        n_human=stats["n_human"],
        n_high_conf=stats["n_high_conf"],
        direction_breakdown=stats["direction_breakdown"],
        evidence_records=stats["evidence_records"],
    )

    if verbose:
        print(f"  Scoring: {method_name} ({stats['n_papers']} papers, "
              f"{stats['n_human']} human)")

    try:
        raw = call_fn(STAGE3_SYSTEM, prompt, model)
        if raw.startswith("```"):
            raw = "\n".join(l for l in raw.split("\n") if not l.startswith("```")).strip()
        result = json.loads(raw)
        result["_stage"]        = 3
        result["_status"]       = "ok"
        result["_n_papers"]     = stats["n_papers"]
        result["_n_human"]      = stats["n_human"]
        result["_low_evidence"] = stats["n_papers"] < MIN_PAPERS_FOR_INDIVIDUAL_SCORE
    except json.JSONDecodeError as exc:
        result = {
            "method_name":         method_name,
            "directionality_score": None,
            "_stage":  3,
            "_status": "json_error",
            "_error":  str(exc),
        }
    except Exception as exc:
        result = {
            "method_name":         method_name,
            "directionality_score": None,
            "_stage":  3,
            "_status": "api_error",
            "_error":  str(exc),
        }

    return result


# ---------------------------------------------------------------------------
# Final summary
# ---------------------------------------------------------------------------

def generate_final_summary(
    call_fn,
    model: str,
    scored: list[dict[str, Any]],
    verbose: bool = False,
) -> dict[str, Any]:
    """Generate the comparative summary and WholeBIF-RDB weights."""
    clean = [
        {k: v for k, v in r.items() if not k.startswith("_")}
        for r in scored
        if r.get("directionality_score") is not None
    ]
    prompt = STAGE3_SUMMARY_USER_TEMPLATE.format(
        n_methods=len(clean),
        scored_json=json.dumps(clean, ensure_ascii=False, indent=2),
    )
    if verbose:
        print("\n[Summary] Generating final comparative summary...")
    try:
        raw = call_fn(STAGE3_SUMMARY_SYSTEM, prompt, model)
        if raw.startswith("```"):
            raw = "\n".join(l for l in raw.split("\n") if not l.startswith("```")).strip()
        return json.loads(raw)
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def print_score_table(scored: list[dict[str, Any]]) -> None:
    print("\n" + "=" * 80)
    print(f"{'Method':<48} {'Score':>7}  {'Papers':>7}  {'Human':>6}")
    print("-" * 80)
    for r in sorted(scored, key=lambda x: x.get("directionality_score") or 0, reverse=True):
        name  = r.get("method_name", "")[:46]
        score = r.get("directionality_score")
        n     = r.get("_n_papers", "?")
        h     = r.get("_n_human",  "?")
        low   = " *" if r.get("_low_evidence") else ""
        s     = f"{score:.2f}" if score is not None else "  ERR"
        print(f"{name:<48} {s:>7}  {n:>7}  {h:>6}{low}")
    print("=" * 80)
    print("* = fewer than", MIN_PAPERS_FOR_INDIVIDUAL_SCORE, "papers — low-evidence score\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> None:
    if args.api == "claude":
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            sys.exit("ERROR: ANTHROPIC_API_KEY not set")
        client = anthropic.Anthropic(api_key=api_key)
        model  = args.model or CLAUDE_MODEL
        call_fn = lambda sys_p, usr_p, m: call_claude(client, sys_p, usr_p, m)
    else:
        from openai import OpenAI
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            sys.exit("ERROR: OPENAI_API_KEY not set")
        client  = OpenAI(api_key=api_key)
        model   = args.model or OPENAI_MODEL
        call_fn = lambda sys_p, usr_p, m: call_openai(client, sys_p, usr_p, m)

    print(f"Stage 3 — Evidence-Grounded Method Scoring")
    print(f"API   : {args.api}  |  Model: {model}")

    index_path = Path(args.input)
    if not index_path.exists():
        sys.exit(f"ERROR: Stage 2 index not found: {index_path}\nRun stage2_extract_methods.py first.")

    with open(index_path, encoding="utf-8") as f:
        index: dict[str, list[dict]] = json.load(f)

    print(f"Loaded index: {len(index)} unique methods")

    # Filter methods with too few papers (still score, but flag)
    methods_items = sorted(index.items(), key=lambda x: -len(x[1]))

    scored = []
    for i, (method_name, evidence_list) in enumerate(methods_items, start=1):
        if args.min_papers and len(evidence_list) < args.min_papers:
            print(f"[{i}/{len(methods_items)}] SKIP {method_name} ({len(evidence_list)} papers < {args.min_papers})")
            continue
        print(f"[{i}/{len(methods_items)}] {method_name} ({len(evidence_list)} papers)")
        result = score_one_method(method_name, evidence_list, call_fn, model, verbose=args.verbose)
        scored.append(result)
        if i < len(methods_items):
            time.sleep(REQUEST_DELAY)

    print_score_table(scored)

    # Final summary
    summary = generate_final_summary(call_fn, model, scored, verbose=args.verbose)

    # Write output
    output = {
        "pipeline_stage": 3,
        "api":   args.api,
        "model": model,
        "n_methods_scored": len(scored),
        "scored_methods": scored,
        "summary": summary,
    }
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"\nResults written to: {out_path.resolve()}")

    if "wholebif_rdb_pder_weights" in summary:
        print("\nWholeBIF-RDB PDER weights:")
        for method, weight in sorted(
            summary["wholebif_rdb_pder_weights"].items(),
            key=lambda x: -x[1]
        ):
            print(f"  {method:<50}  {weight:.2f}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Stage 3: Score methods from evidence")
    p.add_argument("--input",      default=str(DEFAULT_INPUT))
    p.add_argument("--output",     default=str(DEFAULT_OUTPUT))
    p.add_argument("--api",        choices=["claude", "openai"], default="claude")
    p.add_argument("--model",      default=None)
    p.add_argument("--min-papers", type=int, default=None,
                   help="Skip methods with fewer than N papers")
    p.add_argument("--verbose",    action="store_true")
    return p.parse_args()


if __name__ == "__main__":
    run(parse_args())
