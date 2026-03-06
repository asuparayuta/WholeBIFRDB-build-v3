#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
import_bdbra_into_wholebif_v4_enhanced_patched.py
--------------------------------------------------
Import a BDBRA-style CSV into WholeBIF-RDB (PostgreSQL).

Tables written:
  references_tbl  one row per unique reference_id (upsert)
  connections     one row per (sender, receiver, reference) triple (insert, skip on conflict)

Column mapping from CSV to DB:
  reference column  -> references_tbl.title
  DOI               -> references_tbl.doi, doc_link
  BibTeX            -> references_tbl.bibtex, bibtex_link
  journal           -> references_tbl.journal_names
  journalscore      -> connections.journal_score
  methodscore       -> connections.pder_score
  citationscore     -> connections.csi_score
  credibility_rating (mean of three scores)    -> connections.credibility_rating
  summarized_cr (Bayesian-updated, from CSV)   -> connections.summarized_cr

reference_id format:
  Extracted from BibTeX author and year fields: "FamilyName_YYYY" (e.g. "Zhang_2019").
  Falls back to the first 10 characters of the reference title, then the DOI,
  then a timestamp-based generated ID.

VARCHAR(255) columns are truncated to 255 characters by default.
Use --no-truncate to disable this behaviour (may cause database errors).

Changes from v4:
  - summarized_cr is read directly from the CSV column produced by
    compute_summarized_cr.py rather than recomputed here.
    Falls back to the mean of the three score columns when the column is absent.

Changes from v3:
  - reference_id is generated from BibTeX author/year.

Changes from base:
  - references_tbl.title is always taken from the CSV 'reference' column.
"""

import argparse
import csv
import re
import sys
from datetime import datetime
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote

try:
    import psycopg2
    from psycopg2.extras import DictCursor
except Exception:
    print(
        "[ERROR] psycopg2 is required. Install with: pip install psycopg2-binary",
        file=sys.stderr,
    )
    raise


DEFAULTS = dict(
    host="localhost",
    port="5432",
    dbname="wholebif_rdb",
    user="wholebif",
    password="",
)

# VARCHAR(255) columns that are truncated by default
VARCHAR255_COLUMNS = {
    "reference_id", "doc_link", "bibtex_link", "doi", "litterature_type",
    "type", "journal_names", "contributor", "project_id", "reviewer",
}


# ---------------------------------------------------------------------------
# String utilities
# ---------------------------------------------------------------------------

def norm(s: Any) -> str:
    """Normalize a value to a stripped string. Returns empty string for null-like values."""
    if s is None:
        return ""
    if isinstance(s, float):
        return str(int(s)) if s.is_integer() else str(s)
    s = str(s).strip()
    return "" if s.lower() in {"nan", "none", "null"} else s


def first_nonempty(*vals: Any) -> str:
    """Return the first non-empty normalized value, or empty string."""
    for v in vals:
        sv = norm(v)
        if sv:
            return sv
    return ""


def to_float(x: Any) -> Optional[float]:
    try:
        xs = norm(x)
        return float(xs) if xs else None
    except Exception:
        return None


def make_doc_link(doi: str) -> str:
    doi = norm(doi)
    return f"https://doi.org/{doi}" if doi else ""


def make_bibtex_dataurl(bibtex: str) -> str:
    b = norm(bibtex)
    return "data:text/plain;charset=utf-8," + quote(b) if b else ""


def sanitize_id(s: str) -> str:
    return norm(s)


# ---------------------------------------------------------------------------
# BibTeX parsing
# ---------------------------------------------------------------------------

def extract_author_year(bibtex: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract the first author family name and publication year from a BibTeX string.

    Supported author formats:
      "Li Zhang and John Doe"   -> "Zhang"
      "Doe, John and Smith, Jane" -> "Doe"

    Returns (family_name, year), or (None, None) if extraction fails.
    """
    bibtex = norm(bibtex)
    if not bibtex:
        return None, None

    year = None
    year_match = re.search(r"year\s*=\s*\{?(\d{4})\}?", bibtex, re.IGNORECASE)
    if year_match:
        year = year_match.group(1)

    author = None
    author_match = re.search(r"author\s*=\s*\{([^}]+)\}", bibtex, re.IGNORECASE)
    if author_match:
        first = author_match.group(1).strip().split(" and ")[0].strip()
        if "," in first:
            author = first.split(",")[0].strip()
        else:
            words = first.split()
            if words:
                author = words[-1].strip()

    return author, year


def gen_reference_id(reference_text: str, fallback: str = "", bibtex: str = "") -> str:
    """
    Generate a reference_id string.

    Priority:
      1. BibTeX author+year -> "FamilyName_YYYY"
         Truncated to 20 characters if necessary.
      2. First 10 characters of reference_text.
      3. First 10 characters of fallback (e.g. DOI).
      4. Timestamp-based generated ID ("GENYYYYMMDDHHMMSSffffff", truncated to 10).
    """
    author, year = extract_author_year(bibtex)
    if author and year:
        ref_id = f"{author}_{year}"
        if len(ref_id) > 20:
            max_len = 20 - len(year) - 1
            if max_len > 0:
                return f"{author[:max_len]}_{year}"
        return ref_id

    ref = norm(reference_text)
    if ref:
        return ref[:10]
    fb = norm(fallback)
    if fb:
        return fb[:10]
    return ("GEN" + datetime.utcnow().strftime("%Y%m%d%H%M%S%f"))[:10]


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def open_conn(args: argparse.Namespace) -> "psycopg2.connection":
    return psycopg2.connect(
        host=args.host, port=args.port, dbname=args.dbname,
        user=args.user, password=args.password,
    )


def apply_truncation(d: Dict[str, Any], enable: bool) -> Dict[str, Any]:
    if not enable:
        return d
    out: Dict[str, Any] = {}
    for k, v in d.items():
        if v is None:
            out[k] = v
        elif k in VARCHAR255_COLUMNS and len(str(v)) > 255:
            out[k] = str(v)[:255]
        else:
            out[k] = v
    return out


def ensure_references(
    conn: "psycopg2.connection",
    ref_row: Dict[str, Any],
    truncate255: bool = True,
) -> str:
    ref_row = apply_truncation(ref_row, truncate255)
    with conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute(
            """
            INSERT INTO references_tbl (
                reference_id, doc_link, bibtex_link, doi, bibtex,
                litterature_type, type, authors, title, journal_names,
                alternative_url, contributor, project_id, review_results, reviewer
            ) VALUES (
                %(reference_id)s, %(doc_link)s, %(bibtex_link)s, %(doi)s, %(bibtex)s,
                %(litterature_type)s, %(type)s, %(authors)s, %(title)s, %(journal_names)s,
                %(alternative_url)s, %(contributor)s, %(project_id)s,
                %(review_results)s, %(reviewer)s
            )
            ON CONFLICT (reference_id) DO UPDATE SET
                doc_link         = EXCLUDED.doc_link,
                bibtex_link      = EXCLUDED.bibtex_link,
                doi              = EXCLUDED.doi,
                bibtex           = EXCLUDED.bibtex,
                litterature_type = COALESCE(EXCLUDED.litterature_type,
                                            references_tbl.litterature_type),
                type             = COALESCE(EXCLUDED.type, references_tbl.type),
                authors          = COALESCE(EXCLUDED.authors, references_tbl.authors),
                title            = COALESCE(EXCLUDED.title, references_tbl.title),
                journal_names    = COALESCE(EXCLUDED.journal_names,
                                            references_tbl.journal_names),
                alternative_url  = COALESCE(EXCLUDED.alternative_url,
                                            references_tbl.alternative_url),
                contributor      = EXCLUDED.contributor,
                project_id       = COALESCE(EXCLUDED.project_id,
                                            references_tbl.project_id),
                review_results   = COALESCE(EXCLUDED.review_results,
                                            references_tbl.review_results),
                reviewer         = COALESCE(EXCLUDED.reviewer, references_tbl.reviewer)
            """,
            ref_row,
        )
    return ref_row["reference_id"]


def insert_connection(conn: "psycopg2.connection", con_row: Dict[str, Any]) -> bool:
    with conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute(
            """
            INSERT INTO connections (
                sender_circuit_id, receiver_circuit_id, reference_id,
                taxon, measurement_method, pointers_on_literature,
                pointers_on_figure, journal_score, csi_score, pder_score,
                reviewer, credibility_rating, summarized_cr
            ) VALUES (
                %(sender_circuit_id)s, %(receiver_circuit_id)s, %(reference_id)s,
                %(taxon)s, %(measurement_method)s, %(pointers_on_literature)s,
                %(pointers_on_figure)s, %(journal_score)s, %(csi_score)s,
                %(pder_score)s, %(reviewer)s, %(credibility_rating)s, %(summarized_cr)s
            )
            ON CONFLICT (sender_circuit_id, receiver_circuit_id, reference_id)
            DO NOTHING
            """,
            con_row,
        )
    return True


# ---------------------------------------------------------------------------
# Row builders
# ---------------------------------------------------------------------------

def row_to_lowerkey(d: Dict[str, Any]) -> Dict[str, Any]:
    return {(k.lower().strip() if isinstance(k, str) else k): v for k, v in d.items()}


def build_reference_row(ld: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    reference_text   = first_nonempty(ld.get("reference"), ld.get("ref"), ld.get("citation"))
    doi              = first_nonempty(ld.get("doi"), ld.get("dois"))
    bibtex           = first_nonempty(ld.get("bibtex"), ld.get("bibtex_text"), ld.get("bib"))
    journal          = first_nonempty(ld.get("journal"), ld.get("journal_name"), ld.get("journal_names"))
    authors          = first_nonempty(ld.get("authors"), ld.get("author"))
    litterature_type = first_nonempty(ld.get("litterature_type"), ld.get("literature_type"), ld.get("type"))
    typ              = first_nonempty(ld.get("type")) if not litterature_type else ""
    alternative_url  = first_nonempty(ld.get("alternative_url"), ld.get("url"))
    project_id       = norm(ld.get("project_id"))
    review_results   = norm(ld.get("review_results"))
    reviewer         = norm(ld.get("reviewer"))

    reference_id = gen_reference_id(reference_text, fallback=doi, bibtex=bibtex)
    doc_link     = make_doc_link(doi)
    bibtex_link  = make_bibtex_dataurl(bibtex)

    ref_row = dict(
        reference_id     = reference_id,
        doc_link         = doc_link,
        bibtex_link      = bibtex_link,
        doi              = doi,
        bibtex           = bibtex,
        litterature_type = litterature_type,
        type             = typ,
        authors          = authors,
        title            = reference_text,
        journal_names    = journal,
        alternative_url  = alternative_url,
        contributor      = "fromBDBRA",
        project_id       = project_id or None,
        review_results   = review_results or None,
        reviewer         = reviewer or None,
    )
    return reference_id, ref_row


def build_connection_row(
    ld: Dict[str, Any],
    reference_id: str,
) -> Optional[Dict[str, Any]]:
    sender   = sanitize_id(first_nonempty(ld.get("dhbasid"), ld.get("sender_circuit_id"), ld.get("sender")))
    receiver = sanitize_id(first_nonempty(ld.get("dhbarid"), ld.get("receiver_circuit_id"), ld.get("receiver")))
    if not sender or not receiver:
        return None

    taxon    = norm(ld.get("taxon"))
    method   = first_nonempty(ld.get("method"), ld.get("measurement_method"))
    pointer  = first_nonempty(ld.get("pointer"), ld.get("pointers_on_literature"),
                              ld.get("evidence"), ld.get("pointers"))
    figure   = first_nonempty(ld.get("figure"), ld.get("pointers_on_figure"), ld.get("fig"))
    reviewer = norm(ld.get("reviewer"))

    # CSV column mapping:
    #   journalscore  -> journal_score
    #   methodscore   -> pder_score
    #   citationscore -> csi_score
    journal_score = to_float(ld.get("journalscore"))
    pder_score    = to_float(ld.get("methodscore"))
    csi_value     = to_float(ld.get("citationscore"))

    values      = [v for v in (journal_score, pder_score, csi_value) if v is not None]
    credibility = sum(values) / len(values) if values else None

    # Use the pre-computed summarized_cr from compute_summarized_cr.py when available.
    # Fall back to the simple mean when the column is absent or empty.
    summarized = to_float(ld.get("summarized_cr"))
    if summarized is None:
        summarized = credibility

    return dict(
        sender_circuit_id      = sender,
        receiver_circuit_id    = receiver,
        reference_id           = reference_id,
        taxon                  = taxon or None,
        measurement_method     = method or None,
        pointers_on_literature = pointer or None,
        pointers_on_figure     = figure or None,
        journal_score          = journal_score,
        csi_score              = norm(ld.get("citationscore")) or None,
        pder_score             = pder_score,
        reviewer               = reviewer or None,
        credibility_rating     = credibility,
        summarized_cr          = summarized,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Import a BDBRA-style CSV into WholeBIF-RDB "
                    "(references_tbl + connections)."
    )
    ap.add_argument("--csv",          required=True, help="Path to the input CSV.")
    ap.add_argument("--host",         default=DEFAULTS["host"])
    ap.add_argument("--port",         default=DEFAULTS["port"])
    ap.add_argument("--dbname",       default=DEFAULTS["dbname"])
    ap.add_argument("--user",         default=DEFAULTS["user"])
    ap.add_argument("--password",     default=DEFAULTS["password"])
    ap.add_argument("--commit_every", type=int, default=500,
                    help="Number of rows between commits (default: 500).")
    ap.add_argument("--encoding",     default="utf-8",
                    help="CSV file encoding (default: utf-8).")
    ap.add_argument("--errors",       default="replace",
                    help="Encoding error policy: strict / ignore / replace (default: replace).")
    ap.add_argument("--no-truncate",  action="store_true",
                    help="Disable VARCHAR(255) truncation (may raise database errors).")
    args = ap.parse_args()

    conn           = open_conn(args)
    conn.autocommit = False

    total = ok_refs = ok_conns = skipped_conns = batch = 0

    with open(args.csv, "r", newline="", encoding=args.encoding, errors=args.errors) as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            ld = row_to_lowerkey(row)

            reference_id, ref_row = build_reference_row(ld)
            try:
                ensure_references(conn, ref_row, truncate255=(not args.no_truncate))
                ok_refs += 1
            except Exception as e:
                print(
                    f"[ERROR] references_tbl upsert failed at row {total} "
                    f"(reference_id={reference_id}): {e}",
                    file=sys.stderr,
                )
                conn.rollback()
                continue

            con_row = build_connection_row(ld, reference_id)
            if con_row is None:
                skipped_conns += 1
            else:
                try:
                    insert_connection(conn, con_row)
                    ok_conns += 1
                except Exception as e:
                    print(
                        f"[ERROR] connections insert failed at row {total}: {e}",
                        file=sys.stderr,
                    )
                    conn.rollback()
                    continue

            batch += 1
            if batch >= args.commit_every:
                conn.commit()
                batch = 0

    conn.commit()
    conn.close()
    print(f"[DONE] rows processed      : {total}")
    print(f"       references upserted  : {ok_refs}")
    print(f"       connections inserted : {ok_conns}")
    print(f"       connections skipped  : {skipped_conns}  (dhbasid or dhbarid missing)")


if __name__ == "__main__":
    main()
