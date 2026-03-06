#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compute_summarized_cr.py
------------------------
Compute credibility_rating and summarized_cr for each row in a CSV.

Rules:
  Single record (sender+receiver pair appears only once):
    summarized_cr = (journalscore + methodscore + citationscore) / 3

  Multiple records (same sender+receiver pair appears two or more times):
    Bayesian update using a Beta-Binomial model.

Bayesian update details:
  Prior: Beta(alpha0=1, beta0=1)  -- uniform, no prior knowledge assumed.

  Records sharing the same sender+receiver are processed in order.
  Each record's credibility_rating (mean of the three scores) is treated
  as a success probability and used to update the posterior:

      alpha <- alpha + credibility_rating
      beta  <- beta  + (1 - credibility_rating)
      summarized_cr = alpha / (alpha + beta)   # posterior mean after this record

  Effect:
  - The more records that report a projection with high credibility, the closer
    summarized_cr converges to 1.0.
  - Conflicting records pull the score toward an intermediate value.
  - With few records the prior (equivalent to 0.5) has a strong regularizing effect.

Output:
  Writes credibility_rating (simple mean) and summarized_cr (Bayesian result)
  back into the CSV.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from typing import Optional

ALPHA0 = 1.0  # Beta prior parameter (uniform prior)
BETA0  = 1.0


def to_float(val: object) -> Optional[float]:
    try:
        v = str(val).strip()
        if v.lower() in ("", "nan", "none", "null"):
            return None
        return float(v)
    except (ValueError, TypeError):
        return None


def mean_of_scores(
    journal: Optional[float],
    pder: Optional[float],
    csi: Optional[float],
) -> Optional[float]:
    """Return the mean of available scores, ignoring None values."""
    vals = [v for v in (journal, pder, csi) if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def compute_summarized_cr(input_csv: str, output_csv: Optional[str] = None) -> None:
    out_path = output_csv or input_csv

    rows: list[dict] = []
    with open(input_csv, encoding="utf-8-sig", newline="") as f:
        reader     = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows       = list(reader)

    for col in ("credibility_rating", "summarized_cr"):
        if col not in fieldnames:
            fieldnames.append(col)
    for row in rows:
        row.setdefault("credibility_rating", "")
        row.setdefault("summarized_cr", "")

    # Step 1: compute credibility_rating (simple mean) for every row
    for row in rows:
        js  = to_float(row.get("journalscore", ""))
        ms  = to_float(row.get("methodscore",  ""))
        cs  = to_float(row.get("citationscore", ""))
        cr  = mean_of_scores(js, ms, cs)
        row["credibility_rating"] = str(round(cr, 10)) if cr is not None else ""

    # Step 2: group rows by (dhbasid or sender, dhbarid or receiver)
    def group_key(row: dict) -> tuple[str, str]:
        s = row.get("dhbasid", "").strip() or row.get("sender", "").strip().lower()
        r = row.get("dhbarid", "").strip() or row.get("receiver", "").strip().lower()
        return (s, r)

    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for idx, row in enumerate(rows):
        groups[group_key(row)].append(idx)

    # Step 3: compute summarized_cr per group
    for key, indices in groups.items():
        if len(indices) == 1:
            # Single record: use credibility_rating as-is
            row = rows[indices[0]]
            row["summarized_cr"] = row["credibility_rating"]
        else:
            # Multiple records: sequential Bayesian update
            alpha = ALPHA0
            beta  = BETA0
            for idx in indices:
                cr = to_float(rows[idx]["credibility_rating"])
                if cr is None:
                    cr = 0.5  # treat missing score as neutral
                alpha += cr
                beta  += (1.0 - cr)
                posterior_mean = alpha / (alpha + beta)
                rows[idx]["summarized_cr"] = str(round(posterior_mean, 10))

    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    multi_groups = sum(1 for v in groups.values() if len(v) > 1)
    print(
        f"[compute_summarized_cr] {len(rows)} rows, "
        f"{len(groups)} unique projections "
        f"({multi_groups} with multiple records, Bayesian update applied)"
        f" -> {out_path}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Compute credibility_rating (mean of 3 scores) and summarized_cr "
            "(Bayesian update for duplicate sender+receiver pairs)."
        )
    )
    ap.add_argument("--input",  required=True, help="Input CSV")
    ap.add_argument("--output", default=None,  help="Output CSV (default: overwrite input)")
    args = ap.parse_args()
    compute_summarized_cr(args.input, args.output)


if __name__ == "__main__":
    main()
