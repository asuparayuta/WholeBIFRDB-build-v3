#!/usr/bin/env python3
"""
stage1_summarize.py
====================
Stage 1 of the Neural Projection Scoring Pipeline.

Reads a list of papers (CSV or JSON) and generates a structured summary
for each paper using the LLM.

Input  : data/papers_input.csv   (pubmed_id, title, abstract, fulltext*)
Output : data/stage1_summaries.jsonl  (one JSON object per line)

Usage:
    python stage1_summarize.py [--input FILE] [--output FILE]
                               [--api claude|openai] [--model MODEL]
                               [--resume] [--limit N] [--verbose]
"""

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from prompts import STAGE1_SYSTEM, STAGE1_USER_TEMPLATE

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_INPUT  = Path(__file__).parent.parent / "data" / "papers_input.csv"
DEFAULT_OUTPUT = Path(__file__).parent.parent / "data" / "stage1_summaries.jsonl"

CLAUDE_MODEL  = "claude-sonnet-4-6"
OPENAI_MODEL  = "gpt-4.1"
MAX_TOKENS    = 800
TEMPERATURE   = 0.0
REQUEST_DELAY = 0.5   # seconds between API calls


# ---------------------------------------------------------------------------
# LLM call wrappers
# ---------------------------------------------------------------------------

def call_claude(client, prompt_user: str, model: str) -> str:
    import anthropic
    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        system=STAGE1_SYSTEM,
        messages=[{"role": "user", "content": prompt_user}],
    )
    return response.content[0].text.strip()


def call_openai(client, prompt_user: str, model: str) -> str:
    response = client.chat.completions.create(
        model=model,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": STAGE1_SYSTEM},
            {"role": "user",   "content": prompt_user},
        ],
    )
    return response.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# Input reader
# ---------------------------------------------------------------------------

def load_papers(path: Path) -> list[dict[str, str]]:
    """
    Supports CSV and JSON/JSONL.
    Required columns: pubmed_id, title, abstract
    Optional columns: fulltext, year, journal
    """
    suffix = path.suffix.lower()
    papers = []

    if suffix == ".csv":
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                papers.append({
                    "pubmed_id": row.get("pubmed_id", "").strip(),
                    "title":     row.get("title", "").strip(),
                    "abstract":  row.get("abstract", "").strip(),
                    "fulltext":  row.get("fulltext", "").strip(),
                })

    elif suffix in (".json", ".jsonl"):
        with open(path, encoding="utf-8") as f:
            if suffix == ".json":
                data = json.load(f)
                if isinstance(data, list):
                    papers = data
                else:
                    papers = [data]
            else:  # jsonl
                papers = [json.loads(line) for line in f if line.strip()]

    else:
        sys.exit(f"Unsupported input format: {suffix}. Use .csv, .json, or .jsonl")

    print(f"Loaded {len(papers)} papers from {path}")
    return papers


# ---------------------------------------------------------------------------
# Core summarization
# ---------------------------------------------------------------------------

def summarize_paper(
    paper: dict[str, str],
    call_fn,
    model: str,
    verbose: bool = False,
) -> dict[str, Any]:
    """Summarize a single paper. Returns parsed JSON or error dict."""

    pubmed_id = paper.get("pubmed_id", "unknown")
    fulltext_excerpt = (paper.get("fulltext") or "")[:3000]  # cap to avoid token overflow

    prompt = STAGE1_USER_TEMPLATE.format(
        pubmed_id=pubmed_id,
        title=paper.get("title", ""),
        abstract=paper.get("abstract", ""),
        fulltext=fulltext_excerpt or "(not available)",
    )

    if verbose:
        print(f"  Summarising {pubmed_id}: {paper.get('title', '')[:60]}...")

    try:
        raw = call_fn(prompt, model)
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = "\n".join(l for l in raw.split("\n") if not l.startswith("```")).strip()
        result = json.loads(raw)
        result["_stage"] = 1
        result["_status"] = "ok"
    except json.JSONDecodeError as exc:
        result = {
            "pubmed_id": pubmed_id,
            "_stage": 1,
            "_status": "json_error",
            "_error": str(exc),
            "_raw": raw[:500] if "raw" in dir() else "",
        }
    except Exception as exc:
        result = {
            "pubmed_id": pubmed_id,
            "_stage": 1,
            "_status": "api_error",
            "_error": str(exc),
        }

    return result


# ---------------------------------------------------------------------------
# Resume support
# ---------------------------------------------------------------------------

def load_already_done(output_path: Path) -> set[str]:
    """Return set of pubmed_ids already written to output file."""
    done = set()
    if output_path.exists():
        with open(output_path, encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    pid = obj.get("pubmed_id")
                    if pid:
                        done.add(str(pid))
                except Exception:
                    pass
    return done


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> None:
    # ── Client setup ────────────────────────────────────────────────────
    if args.api == "claude":
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            sys.exit("ERROR: ANTHROPIC_API_KEY not set")
        client = anthropic.Anthropic(api_key=api_key)
        model  = args.model or CLAUDE_MODEL
        call_fn = lambda prompt, m: call_claude(client, prompt, m)

    else:  # openai
        from openai import OpenAI
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            sys.exit("ERROR: OPENAI_API_KEY not set")
        client  = OpenAI(api_key=api_key)
        model   = args.model or OPENAI_MODEL
        call_fn = lambda prompt, m: call_openai(client, prompt, m)

    print(f"Stage 1 — Paper Summarization")
    print(f"API   : {args.api}  |  Model: {model}")

    # ── Load papers ──────────────────────────────────────────────────────
    papers = load_papers(args.input)
    if args.limit:
        papers = papers[:args.limit]
        print(f"Limiting to first {args.limit} papers (--limit)")

    # ── Resume ───────────────────────────────────────────────────────────
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    already_done = set()
    if args.resume:
        already_done = load_already_done(output_path)
        print(f"Resume mode: {len(already_done)} papers already done, skipping.")
        papers = [p for p in papers if str(p.get("pubmed_id", "")) not in already_done]

    if not papers:
        print("Nothing to do — all papers already processed.")
        return

    # ── Process ──────────────────────────────────────────────────────────
    n_ok = n_err = 0
    with open(output_path, "a" if args.resume else "w", encoding="utf-8") as out_f:
        for i, paper in enumerate(papers, start=1):
            print(f"[{i}/{len(papers)}] {paper.get('pubmed_id', '?')} — {paper.get('title', '')[:55]}")
            result = summarize_paper(paper, call_fn, model, verbose=args.verbose)

            out_f.write(json.dumps(result, ensure_ascii=False) + "\n")
            out_f.flush()

            if result["_status"] == "ok":
                n_ok += 1
            else:
                n_err += 1
                print(f"  [ERROR] {result.get('_error', '')[:100]}")

            if i < len(papers):
                time.sleep(REQUEST_DELAY)

    print(f"\nStage 1 complete: {n_ok} OK / {n_err} errors")
    print(f"Output: {output_path.resolve()}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Stage 1: Summarise neuroscience papers")
    p.add_argument("--input",   default=str(DEFAULT_INPUT),  help="Input CSV/JSON/JSONL of papers")
    p.add_argument("--output",  default=str(DEFAULT_OUTPUT), help="Output JSONL path")
    p.add_argument("--api",     choices=["claude", "openai"], default="claude")
    p.add_argument("--model",   default=None, help="Override default model")
    p.add_argument("--limit",   type=int, default=None, help="Process only first N papers")
    p.add_argument("--resume",  action="store_true", help="Skip already-processed papers")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


if __name__ == "__main__":
    run(parse_args())
