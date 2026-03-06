#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
enrich_references.py
--------------------
Fill the DOI and BibTeX columns in a CSV using PMID as the lookup key.

Retrieval steps:
  1. NCBI efetch (XML) -> DOI  (batched, 20 PMIDs per request)
  2. CrossRef API (habanero)   -> BibTeX

Rows that already have DOI or BibTeX are skipped.
Set NCBI_API_KEY in the environment to raise the rate limit from 3 to 10 req/s.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
import xml.etree.ElementTree as ET
from typing import Optional

import requests

try:
    from habanero import Crossref
except ImportError:
    print("[ERROR] habanero is required: pip install habanero", file=sys.stderr)
    raise

NCBI_EFETCH    = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
BATCH_SIZE     = 20    # number of PMIDs per efetch request
SLEEP_NCBI     = 0.35  # seconds between requests without an API key (~3 req/s)
SLEEP_CROSSREF = 0.2
BATCH_LOG      = 500


def fetch_dois_from_pmids(pmids: list[str], api_key: Optional[str] = None) -> dict[str, str]:
    """Fetch DOIs for a batch of PMIDs via NCBI efetch. Returns {pmid: doi}."""
    params: dict = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}
    if api_key:
        params["api_key"] = api_key
    try:
        r = requests.get(NCBI_EFETCH, params=params, timeout=60)
        r.raise_for_status()
    except Exception as e:
        print(f"  [WARN] NCBI efetch error: {e}", file=sys.stderr)
        return {}

    result: dict[str, str] = {}
    try:
        root = ET.fromstring(r.text)
    except Exception:
        return result

    for art in root.findall(".//PubmedArticle"):
        pmid = (art.findtext(".//MedlineCitation/PMID") or "").strip()
        if not pmid:
            continue
        doi = ""
        for aid in art.findall(".//ArticleIdList/ArticleId"):
            if aid.attrib.get("IdType", "").lower() == "doi":
                doi = (aid.text or "").strip()
                break
        result[pmid] = doi

    return result


_cr = Crossref(mailto="wholebif@example.com")


def fetch_bibtex(doi: str) -> str:
    """Retrieve BibTeX for a DOI via CrossRef. Returns empty string on failure."""
    if not doi:
        return ""
    time.sleep(SLEEP_CROSSREF)
    try:
        result = _cr.works(ids=doi, format="bibtex")
        if isinstance(result, str):
            return result.strip()
    except Exception as e:
        print(f"  [WARN] CrossRef BibTeX error for {doi}: {e}", file=sys.stderr)
    return ""


def enrich(input_csv: str, output_csv: Optional[str] = None) -> None:
    out_path = output_csv or input_csv
    api_key  = os.getenv("NCBI_API_KEY")
    sleep    = SLEEP_NCBI / 3 if api_key else SLEEP_NCBI

    rows: list[dict] = []
    with open(input_csv, encoding="utf-8-sig", newline="") as f:
        reader     = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows       = list(reader)

    if "BibTex" not in fieldnames:
        fieldnames.append("BibTex")
    for row in rows:
        row.setdefault("BibTex", "")

    # Batch-fetch DOIs only for rows where DOI is missing
    need_doi = [r for r in rows if not r.get("DOI", "").strip() and r.get("PMID", "").strip()]
    pmid_batches = [
        [r["PMID"].strip() for r in need_doi[i:i + BATCH_SIZE]]
        for i in range(0, len(need_doi), BATCH_SIZE)
    ]

    doi_map: dict[str, str] = {}
    for bi, batch in enumerate(pmid_batches):
        if bi > 0 and bi % 10 == 0:
            print(f"  NCBI batch {bi}/{len(pmid_batches)}", file=sys.stderr)
        doi_map.update(fetch_dois_from_pmids(batch, api_key))
        time.sleep(sleep)

    for row in rows:
        if not row.get("DOI", "").strip():
            row["DOI"] = doi_map.get(row.get("PMID", "").strip(), "")

    # Fetch BibTeX per unique DOI
    doi_to_bibtex: dict[str, str] = {}
    for i, row in enumerate(rows):
        if i > 0 and i % BATCH_LOG == 0:
            print(f"  BibTeX {i}/{len(rows)}", file=sys.stderr)
        if row.get("BibTex", "").strip():
            continue
        doi = row.get("DOI", "").strip()
        if not doi:
            continue
        if doi not in doi_to_bibtex:
            doi_to_bibtex[doi] = fetch_bibtex(doi)
        row["BibTex"] = doi_to_bibtex[doi]

    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    doi_filled = sum(1 for r in rows if r.get("DOI", "").strip())
    bib_filled = sum(1 for r in rows if r.get("BibTex", "").strip())
    print(
        f"[enrich_references] {len(rows)} rows, "
        f"DOI: {doi_filled}, BibTeX: {bib_filled} -> {out_path}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Fill DOI and BibTeX columns from PMID.")
    ap.add_argument("--input",  required=True, help="Input CSV")
    ap.add_argument("--output", default=None,  help="Output CSV (default: overwrite input)")
    args = ap.parse_args()
    enrich(args.input, args.output)


if __name__ == "__main__":
    main()
