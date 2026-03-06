#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
enrich_dhba.py
--------------
Match sender/receiver columns in out_gpt52.csv against BrainRegions.csv
and write the best-matching Circuit IDs into dhbasid/dhbarid.

Matching strategy:
  - rapidfuzz.process.extractOne (WRatio) selects the highest-scoring Circuit ID.
  - Rows with scores below MIN_SCORE are left empty.
  - Rows that already have dhbasid/dhbarid are skipped.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from typing import Optional

from rapidfuzz import fuzz, process

MIN_SCORE = 60   # matches below this threshold are discarded
BATCH_LOG = 5000 # progress is printed every N rows


def load_brain_regions(path: str) -> list[tuple[str, str]]:
    """
    Load BrainRegions.csv and return (normalized_name, circuit_id) pairs.
    Parenthetical suffixes are stripped to produce additional candidate entries.
    e.g. "forebrain (prosencephalon)" also yields "forebrain".
    """
    candidates: list[tuple[str, str]] = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            cid   = row.get("Circuit ID", "").strip()
            names = row.get("Names", "").strip()
            if not cid or not names:
                continue
            candidates.append((names.lower(), cid))
            bare = re.sub(r"\s*\(.*?\)", "", names).strip()
            if bare and bare.lower() != names.lower():
                candidates.append((bare.lower(), cid))
    return candidates


class RegionMatcher:
    def __init__(self, brain_regions_csv: str, min_score: int = MIN_SCORE):
        self._candidates = load_brain_regions(brain_regions_csv)
        self._names      = [c[0] for c in self._candidates]
        self._ids        = [c[1] for c in self._candidates]
        self._cache: dict[str, str] = {}
        self._min_score  = min_score

    def match(self, query: str) -> str:
        """Return the best-matching Circuit ID, or empty string if below threshold."""
        q = (query or "").strip().lower()
        if not q:
            return ""
        if q in self._cache:
            return self._cache[q]
        result = process.extractOne(
            q, self._names,
            scorer=fuzz.WRatio,
            score_cutoff=self._min_score,
        )
        cid = self._ids[result[2]] if result else ""
        self._cache[q] = cid
        return cid


def enrich(
    input_csv: str,
    brain_regions_csv: str,
    output_csv: Optional[str] = None,
    min_score: int = MIN_SCORE,
) -> None:
    out_path = output_csv or input_csv
    matcher  = RegionMatcher(brain_regions_csv, min_score=min_score)

    rows: list[dict] = []
    with open(input_csv, encoding="utf-8-sig", newline="") as f:
        reader     = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows       = list(reader)

    changed = 0
    for i, row in enumerate(rows):
        if i > 0 and i % BATCH_LOG == 0:
            print(f"  {i}/{len(rows)} rows processed", file=sys.stderr)

        if not row.get("dhbasid", "").strip():
            matched = matcher.match(row.get("sender", ""))
            row["dhbasid"] = matched
            if matched:
                changed += 1

        if not row.get("dhbarid", "").strip():
            matched = matcher.match(row.get("receiver", ""))
            row["dhbarid"] = matched
            if matched:
                changed += 1

    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[enrich_dhba] {len(rows)} rows, {changed} IDs filled -> {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Attach dhbasid/dhbarid via fuzzy BrainRegion matching."
    )
    ap.add_argument("--input",     required=True, help="Input CSV (out_gpt52.csv format)")
    ap.add_argument("--regions",   required=True, help="Path to BrainRegions.csv")
    ap.add_argument("--output",    default=None,  help="Output CSV (default: overwrite input)")
    ap.add_argument("--min-score", type=int, default=MIN_SCORE,
                    help=f"Minimum fuzzy match score 0-100 (default: {MIN_SCORE})")
    args = ap.parse_args()
    enrich(args.input, args.regions, args.output, min_score=args.min_score)


if __name__ == "__main__":
    main()
