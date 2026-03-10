#!/usr/bin/env python3
"""
stage2_extract_methods.py
==========================
Stage 2 of the Neural Projection Scoring Pipeline.

Reads Stage 1 summaries (JSONL) and extracts experimental methods
from each paper, including directionality metadata.

Input  : data/stage1_summaries.jsonl
Output : data/stage2_methods.jsonl     (one JSON object per paper)
         data/stage2_method_index.json (aggregated: method_name → list of paper evidence)

Usage:
    python stage2_extract_methods.py [--input FILE] [--output FILE]
                                     [--api claude|openai] [--model MODEL]
                                     [--resume] [--limit N] [--verbose]
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from prompts import STAGE2_SYSTEM, STAGE2_USER_TEMPLATE

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_INPUT  = Path(__file__).parent.parent / "data" / "stage1_summaries.jsonl"
DEFAULT_OUTPUT = Path(__file__).parent.parent / "data" / "stage2_methods.jsonl"
INDEX_OUTPUT   = Path(__file__).parent.parent / "data" / "stage2_method_index.json"

CLAUDE_MODEL  = "claude-sonnet-4-6"
OPENAI_MODEL  = "gpt-4.1"
MAX_TOKENS    = 1000
TEMPERATURE   = 0.0
REQUEST_DELAY = 0.5


# ---------------------------------------------------------------------------
# LLM call wrappers
# ---------------------------------------------------------------------------

def call_claude(client, prompt_user: str, model: str) -> str:
    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        system=STAGE2_SYSTEM,
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
            {"role": "system", "content": STAGE2_SYSTEM},
            {"role": "user",   "content": prompt_user},
        ],
    )
    return response.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------

def extract_methods(
    summary: dict[str, Any],
    call_fn,
    model: str,
    verbose: bool = False,
) -> dict[str, Any]:
    """Extract methods from a Stage 1 summary. Returns parsed JSON or error dict."""

    pubmed_id = summary.get("pubmed_id", "unknown")

    # Skip papers that clearly don't involve neural projection tracing
    if not summary.get("uses_neural_projection_tracing", True):
        return {
            "pubmed_id": pubmed_id,
            "methods_found": [],
            "no_methods_found": True,
            "_stage": 2,
            "_status": "skipped_non_projection",
        }

    prompt = STAGE2_USER_TEMPLATE.format(
        summary_json=json.dumps(summary, ensure_ascii=False, indent=2),
        pubmed_id=pubmed_id,
    )

    if verbose:
        print(f"  Extracting methods from {pubmed_id}: {summary.get('title', '')[:55]}...")

    try:
        raw = call_fn(prompt, model)
        if raw.startswith("```"):
            raw = "\n".join(l for l in raw.split("\n") if not l.startswith("```")).strip()
        result = json.loads(raw)
        result["_stage"]  = 2
        result["_status"] = "ok"
    except json.JSONDecodeError as exc:
        result = {
            "pubmed_id": pubmed_id,
            "methods_found": [],
            "_stage": 2,
            "_status": "json_error",
            "_error": str(exc),
        }
    except Exception as exc:
        result = {
            "pubmed_id": pubmed_id,
            "methods_found": [],
            "_stage": 2,
            "_status": "api_error",
            "_error": str(exc),
        }

    return result


# ---------------------------------------------------------------------------
# Index builder
# ---------------------------------------------------------------------------

# Canonical method name normalisation map.
# Keys are substrings that may appear in LLM-produced method names;
# values are canonical names used as keys in the index.
METHOD_NORMALISATION = {
    "dti":                          "DTI tractography",
    "diffusion tensor":             "DTI tractography",
    "tractography":                 "DTI tractography",
    "hardi":                        "HARDI / CSD tractography",
    "spherical deconvolution":      "HARDI / CSD tractography",
    "csd":                          "HARDI / CSD tractography",
    "dii":                          "DiI lipophilic dye tracing",
    "di-i":                         "DiI lipophilic dye tracing",
    "carbocyanine":                 "DiI lipophilic dye tracing",
    "aav anterograde":              "AAV anterograde viral tracing",
    "aav tracer":                   "AAV anterograde viral tracing",
    "anterograde viral":            "AAV anterograde viral tracing",
    "retrograde viral":             "Retrograde viral tracing",
    "raav2-retro":                  "Retrograde viral tracing",
    "retrograde tracer":            "Retrograde viral tracing",
    "ctb":                          "Retrograde viral tracing",
    "cholera toxin":                "Retrograde viral tracing",
    "rabies":                       "Monosynaptic rabies virus tracing",
    "rvdg":                         "Monosynaptic rabies virus tracing",
    "mapseq":                       "MAPseq / BARseq barcode tracing",
    "barseq":                       "MAPseq / BARseq barcode tracing",
    "merge-seq":                    "MERGE-seq projectome+transcriptome",
    "granger":                      "Granger causality (fMRI or EEG)",
    "gca":                          "Granger causality (fMRI or EEG)",
    "dynamic causal":               "Dynamic Causal Modelling (DCM)",
    "dcm":                          "Dynamic Causal Modelling (DCM)",
    "partial directed coherence":   "MEG/EEG PDC/DTF directed connectivity",
    "pdc":                          "MEG/EEG PDC/DTF directed connectivity",
    "directed transfer function":   "MEG/EEG PDC/DTF directed connectivity",
    "dtf":                          "MEG/EEG PDC/DTF directed connectivity",
    "tms-eeg":                      "TMS-EEG",
    "tms–eeg":                      "TMS-EEG",
    "transcranial magnetic":        "TMS-EEG",
    "seeg":                         "SEEG",
    "stereoelectroencephalograph":  "SEEG",
    "ccep":                         "SEEG + CCEP",
    "cortico-cortical evoked":      "SEEG + CCEP",
    "ecog":                         "ECoG subdural electrocorticography",
    "subdural grid":                "ECoG subdural electrocorticography",
    "fmri":                         "fMRI functional connectivity",
    "bold":                         "fMRI functional connectivity",
    "clarity":                      "CLARITY / iDISCO tissue clearing",
    "idisco":                       "CLARITY / iDISCO tissue clearing",
    "autoradiograph":               "Autoradiography",
    "pet":                          "PET connectivity",
    "npi":                          "Neural Perturbational Inference (NPI)",
    "hcp":                          "HCP dMRI (Human Connectome Project)",
}


def normalise_method_name(raw_name: str) -> str:
    """Map an LLM-produced method name to a canonical form."""
    lower = raw_name.lower()
    for key, canonical in METHOD_NORMALISATION.items():
        if key in lower:
            return canonical
    # Fall back to title-cased original
    return raw_name.strip().title()


def build_method_index(
    extraction_records: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """
    Aggregate all per-paper method records into a dict:
      canonical_method_name → list of evidence dicts
    Each evidence dict carries the paper pubmed_id plus the method details.
    """
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for record in extraction_records:
        pubmed_id = record.get("pubmed_id", "unknown")
        for method in record.get("methods_found", []):
            canonical = normalise_method_name(method.get("method_name", "unknown"))
            evidence = {
                "pubmed_id":                   pubmed_id,
                "original_method_name":        method.get("method_name"),
                "method_category":             method.get("method_category"),
                "applied_to_human":            method.get("applied_to_human", False),
                "directionality_type":         method.get("directionality_type"),
                "direction_confidence":        method.get("direction_confidence"),
                "how_direction_was_determined":method.get("how_direction_was_determined"),
                "source_region":               method.get("source_region"),
                "target_region":               method.get("target_region"),
                "evidence_sentence":           method.get("evidence_sentence"),
            }
            index[canonical].append(evidence)

    return dict(index)


# ---------------------------------------------------------------------------
# Resume support
# ---------------------------------------------------------------------------

def load_already_done(output_path: Path) -> set[str]:
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
    if args.api == "claude":
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            sys.exit("ERROR: ANTHROPIC_API_KEY not set")
        client = anthropic.Anthropic(api_key=api_key)
        model  = args.model or CLAUDE_MODEL
        call_fn = lambda p, m: call_claude(client, p, m)
    else:
        from openai import OpenAI
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            sys.exit("ERROR: OPENAI_API_KEY not set")
        client  = OpenAI(api_key=api_key)
        model   = args.model or OPENAI_MODEL
        call_fn = lambda p, m: call_openai(client, p, m)

    print(f"Stage 2 — Method Extraction")
    print(f"API   : {args.api}  |  Model: {model}")

    # Load Stage 1 summaries
    input_path = Path(args.input)
    if not input_path.exists():
        sys.exit(f"ERROR: Stage 1 output not found: {input_path}\nRun stage1_summarize.py first.")

    summaries = []
    with open(input_path, encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line.strip())
                if obj.get("_status") == "ok":
                    summaries.append(obj)
            except Exception:
                pass

    print(f"Loaded {len(summaries)} valid Stage 1 summaries")

    if args.limit:
        summaries = summaries[:args.limit]
        print(f"Limiting to first {args.limit} (--limit)")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    already_done = set()
    if args.resume:
        already_done = load_already_done(output_path)
        summaries = [s for s in summaries if str(s.get("pubmed_id", "")) not in already_done]
        print(f"Resume: {len(already_done)} already done, {len(summaries)} remaining")

    all_records = []
    n_ok = n_err = n_skip = 0

    with open(output_path, "a" if args.resume else "w", encoding="utf-8") as out_f:
        for i, summary in enumerate(summaries, start=1):
            print(f"[{i}/{len(summaries)}] {summary.get('pubmed_id', '?')} — "
                  f"{summary.get('title', '')[:50]}")
            result = extract_methods(summary, call_fn, model, verbose=args.verbose)
            out_f.write(json.dumps(result, ensure_ascii=False) + "\n")
            out_f.flush()
            all_records.append(result)

            status = result["_status"]
            if status == "ok":
                n_ok += 1
                n_methods = len(result.get("methods_found", []))
                if args.verbose:
                    print(f"  → {n_methods} method(s) found")
            elif status.startswith("skipped"):
                n_skip += 1
            else:
                n_err += 1
                print(f"  [ERROR] {result.get('_error', '')[:80]}")

            if i < len(summaries):
                time.sleep(REQUEST_DELAY)

    print(f"\nStage 2 complete: {n_ok} OK / {n_skip} skipped / {n_err} errors")

    # ── Build and save method index (also include already-done records) ──
    print("Building method index...")

    # Reload all records from disk if we were in resume mode
    all_disk_records = []
    with open(output_path, encoding="utf-8") as f:
        for line in f:
            try:
                all_disk_records.append(json.loads(line.strip()))
            except Exception:
                pass

    index = build_method_index(all_disk_records)
    index_path = INDEX_OUTPUT
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    print(f"Method index: {len(index)} unique methods found")
    for method, records in sorted(index.items(), key=lambda x: -len(x[1]))[:10]:
        n_human = sum(1 for r in records if r.get("applied_to_human"))
        print(f"  {method:<50}  {len(records):>4} papers  ({n_human} human)")
    print(f"\nIndex saved to: {index_path.resolve()}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Stage 2: Extract experimental methods")
    p.add_argument("--input",   default=str(DEFAULT_INPUT),  help="Stage 1 JSONL output")
    p.add_argument("--output",  default=str(DEFAULT_OUTPUT), help="Output JSONL path")
    p.add_argument("--api",     choices=["claude", "openai"], default="claude")
    p.add_argument("--model",   default=None)
    p.add_argument("--limit",   type=int, default=None)
    p.add_argument("--resume",  action="store_true")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


if __name__ == "__main__":
    run(parse_args())
