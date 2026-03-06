#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
score_records.py
----------------
Compute journalscore, methodscore, and citationscore for each row in a CSV.

  journalscore  : 1.0 for peer-reviewed journals, 0.5 for preprints or unknown.
  methodscore   : suitability of the experimental method for confirming neural
                  projections between brain regions (0.0 to 1.0).
  citationscore : sentiment score derived from abstracts of up to 5 citing papers.
                  Obtained via NCBI elink + Claude API.
                  1.0 = citing paper builds on or supports the cited work.
                  0.5 = neutral citation.
                  0.0 = citing paper disputes or fails to replicate the cited work.

Requirements:
  pip install requests

Environment variables:
  ANTHROPIC_API_KEY  required for citationscore (defaults to 0.5 if unset)
  NCBI_API_KEY       optional, raises NCBI rate limit from 3 to 10 req/s
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from typing import Optional

import requests

EUTILS        = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

SLEEP_NCBI    = 0.35
MAX_CITATIONS = 5
BATCH_LOG     = 500


# ---------------------------------------------------------------------------
# journalscore
# ---------------------------------------------------------------------------

_PREPRINT_PATTERNS = [
    "biorxiv", "medrxiv", "arxiv", "preprint", "psyarxiv",
    "chemrxiv", "researchsquare", "ssrn",
]


def journal_score(journal_name: str) -> float:
    """Return 1.0 for peer-reviewed journals, 0.5 for preprints or unknown sources."""
    jl = (journal_name or "").lower().strip()
    if not jl:
        return 0.5
    for p in _PREPRINT_PATTERNS:
        if p in jl:
            return 0.5
    return 1.0


# ---------------------------------------------------------------------------
# methodscore
#
# Scores reflect how directly a given method can confirm axonal projections
# between brain regions. Methods that provide anatomical, single-synapse
# resolution score highest; indirect functional correlates score lowest.
#
# 1.00  EM connectomics               Direct synaptic observation at nanometer scale.
# 0.97  Monosynaptic viral tracing    delta-G rabies, PRV-Bartha. Proves direct synaptic contact.
# 0.95  Anterograde classical tracer  BDA, PHA-L, WGA-HRP. Visualizes axon terminals directly.
# 0.93  Retrograde classical tracer   CTB, Fluoro-Gold, RetroBeads. Identifies projection neurons.
# 0.92  AAV anterograde tracing       Cell-type specificity available.
# 0.90  CAV-2 retrograde tracing      Effective for long-distance projections.
# 0.88  Optogenetic circuit mapping   ChR2 + patch clamp. Proves functional monosynaptic contact.
# 0.87  Tissue clearing + tracing     CLARITY, iDISCO, CUBIC. Whole-brain projection mapping.
# 0.85  Polysynaptic viral tracing    Rabies, PRV, HSV. Less strict: transsynaptic, not monosynaptic.
# 0.85  Paired patch clamp            Direct measurement of single synaptic connections.
# 0.82  Confocal + tracer             Morphological confirmation of axon terminals.
# 0.80  Antidromic stimulation        Confirms projections via retrograde axonal excitation.
# 0.75  Chemogenetics (DREADDs)       Confirms functional influence, not anatomical connection.
# 0.72  In vivo optogenetics          Functional manipulation only.
# 0.70  Two-photon calcium imaging    Activity observation; not direct projection evidence.
# 0.68  High-density electrophysiol.  Neuropixels, silicon probes, tetrodes.
# 0.68  Patch clamp (single cell)     Electrophysiological measurement.
# 0.65  Single-unit recording         Activity observation.
# 0.65  Calcium imaging (general)     GCaMP, miniscope, fiber photometry.
# 0.65  LFP / EEG                     Indirect functional measure.
# 0.55  Microstimulation              Circuit inference from stimulation-response.
# 0.50  Lesion / inactivation         Projection inference possible but confounded.
# 0.45  DTI / diffusion MRI           Anatomical estimation; high false-positive rate.
# 0.42  Probabilistic tractography    Higher uncertainty than DTI.
# 0.40  Structural MRI connectivity   Indirect anatomical estimate.
# 0.35  Task fMRI connectivity        Functional correlation only.
# 0.32  Resting-state fMRI            Functional correlation; no direct projection evidence.
# 0.30  PET connectivity              Metabolic correlation.
# 0.28  EEG / MEG coherence           Scalp-level indirect measure.
# 0.28  TMS / tDCS                    Non-invasive brain stimulation; indirect inference.
# 0.25  Behavioral correlation        Indirect inference from behavior only.
# 0.25  Computational model           No experimental evidence.
# 0.20  Review / meta-analysis        Synthesis of existing literature.
# 0.15  Textbook description          No primary source cited.
# ---------------------------------------------------------------------------

_METHOD_RULES: list[tuple[list[str], float]] = [
    (["electron microscopy", "em connectom", "serial block", "sbem",
      "fib-sem", "fibsem", "sstem", "tem connectom",
      "array tomography", "cryo-em connectom"],                              1.00),
    (["monosynaptic", "deltag", "delta g rabies", "sad-b19",
      "rvdg", "rv-dg", "rabies deltag", "g-deleted rabies",
      "pseudorabies bartha", "prv-bartha"],                                  0.97),
    (["pha-l", "phaseolus vulgaris", "wga-hrp", "wga hrp",
      "wheat germ agglutinin", "biotinylated dextran", "bda",
      "anterograde trac"],                                                   0.95),
    (["cholera toxin", "ctb", "fluoro-gold", "fluorogold",
      "fast blue", "diamidino yellow", "retrobeads",
      "true blue", "nuclear yellow", "retrograde trac"],                     0.93),
    (["aav anterograde", "adeno-associated virus anterograde",
      "aav-cre anterograde", "cre-dependent aav",
      "aav axon", "aav-gfp anterograde"],                                    0.92),
    (["cav-2", "canine adenovirus"],                                         0.90),
    (["cracm", "channelrhodopsin-assisted circuit",
      "laser-scanning photostimulation",
      "optogenetic.*circuit map", "circuit map.*opto"],                      0.88),
    (["clarity", "idisco", "cubic", "3disco",
      "light sheet.*trac", "trac.*light sheet",
      "whole.brain trac", "tissue clear"],                                   0.87),
    (["rabies", "prv", "pseudorabies", "hsv",
      "herpes simplex", "transsynaptic", "transneuronal",
      "polysynaptic", "multisynaptic"],                                      0.85),
    (["dual patch", "paired patch", "paired recording",
      "double patch", "whole.cell.*monosynaptic"],                           0.85),
    (["confocal.*trac", "trac.*confocal",
      "immunohistochem.*trac", "fluorescence microscop.*trac"],              0.82),
    (["antidromic", "retrograde stimulation",
      "collision test", "axon stimulation"],                                 0.80),
    (["dreadd", "hm3dq", "hm4di",
      "clozapine-n-oxide", "cno", "chemogeneti", "designer receptor"],       0.75),
    (["in vivo.*opto", "opto.*in vivo", "optogeneti",
      "archaerhodopsin", "halorhodopsin", "chr2",
      "channelrhodopsin", "opsins"],                                         0.72),
    (["two-photon", "2-photon", "two photon",
      "gcamp.*imag", "calcium imag.*two"],                                   0.70),
    (["neuropixel", "silicon probe", "multi-electrode array",
      "utah array", "tetrode", "laminar probe"],                             0.68),
    (["patch clamp", "patch-clamp", "whole-cell recording",
      "whole cell record", "voltage clamp", "current clamp"],                0.68),
    (["single unit", "single-unit", "extracellular record",
      "multiunit", "multi-unit", "spike sort"],                              0.65),
    (["calcium imag", "gcamp", "rcamp", "miniscope",
      "fibre photom", "fiber photom"],                                       0.65),
    (["local field potential", "lfp", "electroencephalograph"],              0.65),
    (["microstimulation", "intracortical stimulation",
      "deep brain stimulation"],                                              0.55),
    (["lesion", "inactivation", "muscimol",
      "lidocaine", "tetrodotoxin", "ttx",
      "excitotoxic", "ibotenic", "ablat"],                                   0.50),
    (["dti", "diffusion tensor", "diffusion mri", "diffusion-weighted",
      "mrtrix", "fsl.*tract", "tract.*fsl",
      "probabilistic tractograph", "deterministic tractograph",
      "tractograph", "dwi", "fwc-dmri", "fwc-dti",
      "free water corrected diffusion"],                                     0.45),
    (["voxel-based morphometry", "vbm",
      "grey matter covariance", "cortical thickness correlation"],           0.40),
    (["task.*fmri", "fmri.*task",
      "psychophysiological interaction", "ppi",
      "granger causality", "dynamic causal model", "dcm"],                  0.35),
    (["resting.state", "rs-fmri", "rsfmri",
      "bold.*resting", "functional connectivity.*rest",
      "default mode", "salience network",
      "functional connectivity", " fmri ",
      "bold signal", "functional mri", "functional magnetic"],              0.32),
    (["pet scan", "positron emission", "fdg-pet", "pet.*metaboli"],          0.30),
    (["eeg coherence", "magnetoencephalograph", "meg",
      "phase synchrony", "source imaging"],                                  0.28),
    (["transcranial magnetic", "tms",
      "transcranial direct", "tdcs",
      "non-invasive brain stimulation"],                                      0.28),
    (["behavioral.*correlat", "correlation.*behavior",
      "regression.*connectivity", "seed-based",
      "stimulation"],                                                         0.25),
    (["computational model", "neural model", "simulation",
      "network model", "connectome model", "graph theoreti"],                0.25),
    (["systematic review", "meta-analysis", "literature review"],            0.20),
    (["textbook", "atlas", "classic description"],                           0.15),
]

_METHOD_FLAT: list[tuple[str, float]] = [
    (pat, score) for patterns, score in _METHOD_RULES for pat in patterns
]


def method_score(method: str) -> float:
    """
    Match the method string against _METHOD_FLAT and return the highest-scoring match.
    Returns 0.5 if the string is empty or no pattern matches.
    """
    ml = (method or "").lower()
    if not ml:
        return 0.50
    best: Optional[float] = None
    for pat, score in _METHOD_FLAT:
        if re.search(pat, ml):
            if best is None or score > best:
                best = score
    return best if best is not None else 0.50


# ---------------------------------------------------------------------------
# citationscore
# ---------------------------------------------------------------------------

_session = requests.Session()


def _ncbi_get_json(endpoint: str, params: dict) -> Optional[dict]:
    api_key = os.getenv("NCBI_API_KEY")
    if api_key:
        params["api_key"] = api_key
    try:
        time.sleep(SLEEP_NCBI)
        r = _session.get(f"{EUTILS}/{endpoint}", params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  [WARN] NCBI {endpoint}: {e}", file=sys.stderr)
        return None


def _fetch_citing_pmids(pmid: str) -> list[str]:
    """Use NCBI elink to retrieve PMIDs of papers that cite the given PMID."""
    data = _ncbi_get_json("elink.fcgi", {
        "dbfrom": "pubmed", "db": "pubmed",
        "id": pmid, "linkname": "pubmed_pubmed_citedin",
        "retmode": "json",
    })
    if not data:
        return []
    try:
        links = data["linksets"][0]["linksetdbs"][0]["links"]
        return [str(l) for l in links[:MAX_CITATIONS]]
    except (KeyError, IndexError):
        return []


def _fetch_abstract(pmid: str) -> str:
    """Retrieve the abstract text for a PMID via NCBI efetch."""
    api_key = os.getenv("NCBI_API_KEY")
    params  = {"db": "pubmed", "id": pmid, "retmode": "xml"}
    if api_key:
        params["api_key"] = api_key
    try:
        time.sleep(SLEEP_NCBI)
        r = _session.get(f"{EUTILS}/efetch.fcgi", params=params, timeout=30)
        r.raise_for_status()
        root  = ET.fromstring(r.text)
        parts = [
            (t.text or "").strip()
            for t in root.findall(".//Abstract/AbstractText")
            if (t.text or "").strip()
        ]
        return " ".join(parts)
    except Exception as e:
        print(f"  [WARN] efetch abstract {pmid}: {e}", file=sys.stderr)
        return ""


def _score_sentiments_with_claude(contexts: list[str], api_key: str) -> list[float]:
    """
    Send a list of citing-paper abstracts to Claude and receive one sentiment score
    per abstract (0.0 to 1.0).
    Returns [0.5, ...] if the API call fails.
    """
    if not contexts or not api_key:
        return [0.5] * len(contexts)

    numbered = "\n\n".join(f"[{i+1}]\n{ctx[:800]}" for i, ctx in enumerate(contexts))
    prompt = (
        "You are assessing how citing papers treat a specific neuroscience study.\n"
        "Below are abstracts from papers that cite the study in question.\n\n"
        "For each abstract, output a score from 0.0 to 1.0:\n"
        "  1.0 = builds upon, reproduces, or strongly supports the cited study\n"
        "  0.5 = neutral or background citation\n"
        "  0.0 = questions, contradicts, or reports failure to replicate the cited study\n\n"
        "Return ONLY a JSON array of numbers, one per abstract.\n"
        "Example for 3 abstracts: [0.9, 0.5, 0.1]\n\n"
        f"{numbered}"
    )
    try:
        r = requests.post(
            ANTHROPIC_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 128,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        r.raise_for_status()
        text  = r.json()["content"][0]["text"].strip()
        match = re.search(r"\[[\d.,\s]+\]", text)
        if match:
            scores = json.loads(match.group())
            while len(scores) < len(contexts):
                scores.append(0.5)
            return [max(0.0, min(1.0, float(s))) for s in scores[:len(contexts)]]
    except Exception as e:
        print(f"  [WARN] Claude sentiment: {e}", file=sys.stderr)
    return [0.5] * len(contexts)


def citation_score(pmid: str, doi: str, api_key: Optional[str]) -> float:
    """
    Retrieve up to MAX_CITATIONS citing papers via NCBI elink, fetch their abstracts,
    and return the mean sentiment score computed by Claude.
    Returns 0.5 when no data can be retrieved.
    """
    pmid = (pmid or "").strip()
    if not pmid:
        return 0.5

    citing_pmids = _fetch_citing_pmids(pmid)
    if not citing_pmids:
        return 0.5

    contexts: list[str] = []
    for c_pmid in citing_pmids[:MAX_CITATIONS]:
        abstract = _fetch_abstract(c_pmid)
        if abstract:
            contexts.append(abstract)

    if not contexts:
        return 0.5

    scores = _score_sentiments_with_claude(contexts, api_key or "")
    return round(sum(scores) / len(scores), 10)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def score(
    input_csv: str,
    output_csv: Optional[str] = None,
    skip_citation: bool = False,
) -> None:
    out_path = output_csv or input_csv
    api_key  = os.getenv("ANTHROPIC_API_KEY")

    if not skip_citation and not api_key:
        print(
            "[WARN] ANTHROPIC_API_KEY is not set. citationscore will be fixed at 0.5.",
            file=sys.stderr,
        )

    rows: list[dict] = []
    with open(input_csv, encoding="utf-8-sig", newline="") as f:
        reader     = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows       = list(reader)

    for col in ("journalscore", "methodscore", "citationscore"):
        if col not in fieldnames:
            fieldnames.append(col)
    for row in rows:
        for col in ("journalscore", "methodscore", "citationscore"):
            row.setdefault(col, "")

    for i, row in enumerate(rows):
        if i > 0 and i % BATCH_LOG == 0:
            print(f"  scoring {i}/{len(rows)}", file=sys.stderr)

        if not row.get("journalscore", "").strip():
            row["journalscore"] = str(journal_score(row.get("journal", "")))

        if not row.get("methodscore", "").strip():
            row["methodscore"] = str(method_score(row.get("Method", "")))

        if not skip_citation and not row.get("citationscore", "").strip():
            pmid = row.get("PMID", "").strip()
            doi  = row.get("DOI",  "").strip()
            if pmid or doi:
                row["citationscore"] = str(citation_score(pmid, doi, api_key))

    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[score_records] {len(rows)} rows scored -> {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Compute journalscore / methodscore / citationscore for each row."
    )
    ap.add_argument("--input",  required=True, help="Input CSV")
    ap.add_argument("--output", default=None,  help="Output CSV (default: overwrite input)")
    ap.add_argument("--skip-citation", action="store_true",
                    help="Skip citationscore (no NCBI or Claude API calls)")
    args = ap.parse_args()
    score(args.input, args.output, skip_citation=args.skip_citation)


if __name__ == "__main__":
    main()
