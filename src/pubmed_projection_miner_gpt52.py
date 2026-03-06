\
# -*- coding: utf-8 -*-
"""
PubMed Projection Miner (GPT-5.2, Responses API)

- Searches PubMed via NCBI E-utilities
- Fetches abstract text (and optionally additional text sources later)
- Uses OpenAI Responses API + Structured Outputs (Pydantic) to extract projection records
- Writes a CSV with a stable header, even if 0 rows are extracted (useful for smoke tests)

This script is designed to be practical and robust for long runs with resume support.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import requests
import xml.etree.ElementTree as ET
from tqdm import tqdm

try:
    from openai import OpenAI
except Exception as e:
    raise RuntimeError(
        "Missing dependency: openai. Install with: pip install -r requirements.txt"
    ) from e

from pydantic import BaseModel, Field

from prompts_gpt52 import SYSTEM_PROMPT, USER_TEMPLATE


NCBI_EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
NCBI_DB = "pubmed"

# NCBI esearch history has a limit of ~10000 for retstart
NCBI_RETSTART_LIMIT = 9900


# -----------------------------
# Structured output schema
# -----------------------------
class ProjectionItem(BaseModel):
    sender: str = Field(default="")
    receiver: str = Field(default="")
    dhbasid: str = Field(default="")  # optional: you can fill via DHBA normalization
    dhbarid: str = Field(default="")
    reference: str = Field(default="")
    journal: str = Field(default="")
    DOI: str = Field(default="")
    Taxon: str = Field(default="")
    Method: str = Field(default="")
    Pointer: str = Field(default="")
    Figure: str = Field(default="")

class Extraction(BaseModel):
    items: List[ProjectionItem] = Field(default_factory=list)


# -----------------------------
# Utilities
# -----------------------------
def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def safe_sleep(seconds: float):
    # Keep long runs friendly to NCBI; even with an API key, avoid hammering.
    if seconds > 0:
        time.sleep(seconds)


def read_text_file(path: str) -> str:
    return Path(path).read_text(encoding="utf-8").strip()


def ensure_parent_dir(filepath: str):
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)


def write_csv_header_if_missing(out_csv: str, header: List[str]) -> None:
    """Create CSV (header-only) if it does not exist yet."""
    ensure_parent_dir(out_csv)
    if not Path(out_csv).exists():
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=header,
                quoting=csv.QUOTE_ALL,
                escapechar="\\",
                doublequote=True,
            )
            writer.writeheader()


def append_csv_rows(out_csv: str, header: List[str], rows: List[Dict[str, str]]) -> None:
    """Append rows (dicts) to CSV. Assumes header already exists.

    We force a robust CSV dialect because extracted text can include commas, quotes, or newlines.
    """
    ensure_parent_dir(out_csv)
    with open(out_csv, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=header,
            quoting=csv.QUOTE_ALL,
            escapechar="\\",
            doublequote=True,
        )
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in header})
# -----------------------------
# PubMed client
# -----------------------------
@dataclass
class PubMedHistory:
    webenv: str
    query_key: str
    count: int
    query: str


class PubMedClient:
    def __init__(self, email: str, api_key: str, tool: str = "pubmed_projection_miner", retries: int = 6, timeout: int = 60, backoff: float = 1.5):
        self.email = email
        self.api_key = api_key
        self.tool = tool
        self.session = requests.Session()
        self.retries = retries
        self.timeout = timeout
        self.backoff = backoff

    def _params(self) -> Dict[str, str]:
        return {"email": self.email, "api_key": self.api_key, "tool": self.tool}


    def _get_json_with_retries(self, url: str, params: Dict[str, str]) -> Dict:
        """GET and parse JSON with retries.

        NCBI sometimes returns HTML error pages or JSON with invalid control chars.
        We retry and sanitize control characters if needed.
        """
        last_exc = None
        for attempt in range(1, self.retries + 1):
            try:
                r = self.session.get(url, params=params, timeout=self.timeout)
                r.raise_for_status()
                ct = (r.headers.get('Content-Type') or '').lower()
                txt = r.text
                if 'html' in ct or txt.lstrip().startswith('<'):
                    raise ValueError(f'Non-JSON (likely HTML) response from NCBI. status={r.status_code}, ct={ct}')
                try:
                    return r.json()
                except Exception:
                    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", txt)
                    return json.loads(cleaned)
            except Exception as e:
                last_exc = e
                time.sleep(min(60.0, self.backoff * attempt))
        raise last_exc

    def _get_with_retries(self, url: str, params: Dict[str, str]) -> requests.Response:
        """GET with retries, returning the raw Response object (for XML parsing)."""
        last_exc = None
        for attempt in range(1, self.retries + 1):
            try:
                r = self.session.get(url, params=params, timeout=self.timeout)
                r.raise_for_status()
                return r
            except Exception as e:
                last_exc = e
                time.sleep(min(60.0, self.backoff * attempt))
        raise last_exc

    def esearch_history(self, query: str) -> PubMedHistory:
        """Run esearch with usehistory=y and return WebEnv/QueryKey/Count.

        We use retmode=xml because NCBI occasionally returns malformed JSON responses.
        """
        url = f"{NCBI_EUTILS_BASE}/esearch.fcgi"
        params = {
            "db": NCBI_DB,
            "term": query,
            "retmode": "xml",
            "usehistory": "y",
            "retmax": "0",
        }
        params.update(self._params())

        r = self._get_with_retries(url, params=params)
        root = ET.fromstring(r.text)

        def _text(tag: str) -> str:
            el = root.find(f".//{tag}")
            return (el.text or "").strip() if el is not None else ""

        webenv = _text("WebEnv")
        query_key = _text("QueryKey")
        count_s = _text("Count")
        count = int(count_s) if count_s.isdigit() else 0

        return PubMedHistory(webenv=webenv, query_key=query_key, count=count, query=query)

    def esearch_count(self, query: str) -> int:
        """Get the count of results for a query without creating history."""
        url = f"{NCBI_EUTILS_BASE}/esearch.fcgi"
        params = {
            "db": NCBI_DB,
            "term": query,
            "retmode": "xml",
            "retmax": "0",
        }
        params.update(self._params())
        r = self._get_with_retries(url, params=params)
        root = ET.fromstring(r.text)
        el = root.find(".//Count")
        count_s = (el.text or "").strip() if el is not None else ""
        return int(count_s) if count_s.isdigit() else 0

    def fetch_id_batch(self, history: PubMedHistory, retstart: int, retmax: int) -> List[str]:
        """Fetch a page of PMIDs from an esearch history (retmode=xml)."""
        url = f"{NCBI_EUTILS_BASE}/esearch.fcgi"
        params = {
            "db": NCBI_DB,
            "query_key": history.query_key,
            "WebEnv": history.webenv,
            "retmode": "xml",
            "retstart": str(retstart),
            "retmax": str(retmax),
        }
        params.update(self._params())

        r = self._get_with_retries(url, params=params)
        root = ET.fromstring(r.text)
        ids = [el.text.strip() for el in root.findall(".//IdList/Id") if el.text and el.text.strip()]
        return ids

    def esummary(self, pmids: List[str]) -> Dict[str, Dict[str, str]]:
        if not pmids:
            return {}
        url = f"{NCBI_EUTILS_BASE}/esummary.fcgi"
        params = {
            "db": NCBI_DB,
            "id": ",".join(pmids),
            "retmode": "json",
        }
        params.update(self._params())
        data = self._get_json_with_retries(url, params)["result"]
        out: Dict[str, Dict[str, str]] = {}
        for pmid in pmids:
            rec = data.get(pmid, {})
            out[pmid] = {
                "title": rec.get("title", "") or "",
                "journal": rec.get("fulljournalname", "") or rec.get("source", "") or "",
                "pubdate": rec.get("pubdate", "") or "",
                "doi": "",  # DOI is not reliably in esummary; we'll try efetch parsing separately if needed.
            }
        return out

    def efetch_abstracts(self, pmids: List[str]) -> Dict[str, str]:
        """
        Fetch abstracts in XML and return {pmid: abstract_text}.
        """
        if not pmids:
            return {}
        url = f"{NCBI_EUTILS_BASE}/efetch.fcgi"
        params = {
            "db": NCBI_DB,
            "id": ",".join(pmids),
            "retmode": "xml",
        }
        params.update(self._params())
        r = self.session.get(url, params=params, timeout=60)
        r.raise_for_status()
        xml = r.text

        # Very lightweight parsing (good enough for abstracts); avoids extra deps.
        # We extract each <PubmedArticle> separately, then PMID and AbstractText.
        out: Dict[str, str] = {}
        for art in re.findall(r"<PubmedArticle>.*?</PubmedArticle>", xml, flags=re.S):
            pm = re.search(r"<PMID[^>]*>(\d+)</PMID>", art)
            if not pm:
                continue
            pmid = pm.group(1)
            abs_parts = re.findall(r"<AbstractText[^>]*>(.*?)</AbstractText>", art, flags=re.S)
            if abs_parts:
                # Remove tags inside and unescape minimal entities
                cleaned = []
                for p in abs_parts:
                    p2 = re.sub(r"<.*?>", "", p)
                    p2 = p2.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
                    p2 = re.sub(r"\s+", " ", p2).strip()
                    if p2:
                        cleaned.append(p2)
                out[pmid] = " ".join(cleaned).strip()
            else:
                out[pmid] = ""
        return out


# -----------------------------
# Resume state
# -----------------------------
def load_state(state_path: str) -> Dict:
    if Path(state_path).exists():
        return json.loads(Path(state_path).read_text(encoding="utf-8"))
    return {}


def save_state(state_path: str, state: Dict) -> None:
    ensure_parent_dir(state_path)
    Path(state_path).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_processed_set(processed_path: str) -> set:
    if Path(processed_path).exists():
        return set(Path(processed_path).read_text(encoding="utf-8").split())
    return set()


def append_processed(processed_path: str, pmid: str) -> None:
    ensure_parent_dir(processed_path)
    with open(processed_path, "a", encoding="utf-8") as f:
        f.write(pmid + "\n")


# -----------------------------
# OpenAI extraction
# -----------------------------

# JSON Schema for Structured Outputs (strict)
# We keep the schema simple to match the subset supported in strict mode.
EXTRACTION_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "sender": {"type": "string"},
                    "receiver": {"type": "string"},
                    "dhbasid": {"type": "string"},
                    "dhbarid": {"type": "string"},
                    "reference": {"type": "string"},
                    "journal": {"type": "string"},
                    "DOI": {"type": "string"},
                    "Taxon": {"type": "string"},
                    "Method": {"type": "string"},
                    "Pointer": {"type": "string"},
                    "Figure": {"type": "string"},
                },
                "required": [
                    "sender","receiver","dhbasid","dhbarid","reference","journal",
                    "DOI","Taxon","Method","Pointer","Figure"
                ],
            },
        }
    },
    "required": ["items"],
}

def _responses_output_text(resp) -> str:
    """Best-effort extraction of the text output from a Responses API response."""
    # Newer SDKs provide this helper:
    if hasattr(resp, "output_text") and isinstance(getattr(resp, "output_text"), str):
        return resp.output_text

    out = []
    output = getattr(resp, "output", None)
    if output is None:
        # fallback to dict-like
        output = resp.get("output", []) if isinstance(resp, dict) else []
    for item in output or []:
        # item may be dict or have attributes
        content = item.get("content", []) if isinstance(item, dict) else getattr(item, "content", [])
        for c in content or []:
            ctype = c.get("type") if isinstance(c, dict) else getattr(c, "type", None)
            if ctype in ("output_text", "text"):
                txt = c.get("text") if isinstance(c, dict) else getattr(c, "text", "")
                if txt:
                    out.append(txt)
    return "".join(out).strip()


def extract_with_gpt52(
    client: OpenAI,
    model: str,
    title: str,
    journal: str,
    doi: str,
    snippet: str,
    temperature: float = 0.0,
    max_output_tokens: int = 1500,
) -> Extraction:
    # Keep snippet bounded so outputs stay small and less likely to hit max tokens.
    if snippet and len(snippet) > 6000:
        snippet = snippet[:6000] + " …"

    user_msg = USER_TEMPLATE.format(title=title, journal=journal, doi=doi, snippet=snippet)

    resp = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "extraction",
                "strict": True,
                "schema": EXTRACTION_JSON_SCHEMA,
            }
        },
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )

    raw = _responses_output_text(resp)
    data = json.loads(raw)
    return Extraction.model_validate(data)



# -----------------------------
# CLI command: mine
# -----------------------------
CSV_HEADER = [
    "sender",
    "receiver",
    "dhbasid",
    "dhbarid",
    "reference",
    "journal",
    "DOI",
    "Taxon",
    "Method",
    "Pointer",
    "Figure",
    "PMID",
]


def generate_year_chunks(base_query: str, start_year: int, end_year: int) -> List[Tuple[str, int, int]]:
    """Generate list of (query_with_date_filter, year_start, year_end) tuples.
    
    Each chunk covers one year to stay under NCBI's retstart limit.
    """
    chunks = []
    for year in range(end_year, start_year - 1, -1):  # newest first
        year_query = f"({base_query}) AND ({year}[pdat])"
        chunks.append((year_query, year, year))
    return chunks


def find_year_range_for_query(pubmed: "PubMedClient", query: str) -> Tuple[int, int]:
    """Find approximate year range by checking counts at boundary years."""
    import datetime
    current_year = datetime.datetime.now().year
    
    # Start from current year and go back
    start_year = 1900  # PubMed doesn't go much earlier
    end_year = current_year
    
    # Quick check: does the query have any results in the last 50 years?
    test_query = f"({query}) AND (1975:{current_year}[pdat])"
    count = pubmed.esearch_count(test_query)
    if count == 0:
        # Try even older
        start_year = 1900
    else:
        start_year = 1975
    
    return start_year, end_year


def cmd_mine(args: argparse.Namespace) -> int:
    # Resolve credentials (args first, then env)
    ncbi_email = args.email or os.getenv("NCBI_EMAIL", "")
    ncbi_key = args.api_key or os.getenv("NCBI_API_KEY", "")
    if not ncbi_email or not ncbi_key:
        raise SystemExit("NCBI email/api_key is required (args or env: NCBI_EMAIL, NCBI_API_KEY).")

    openai_key = args.openai_api_key or os.getenv("OPENAI_API_KEY", "")
    if not openai_key:
        raise SystemExit("OpenAI API key is required (args or env: OPENAI_API_KEY).")

    # Output CSV is created upfront (header-only) for smoke tests
    write_csv_header_if_missing(args.out_csv, CSV_HEADER)

    pubmed = PubMedClient(email=ncbi_email, api_key=ncbi_key, tool=args.ncbi_tool, retries=args.ncbi_retries, timeout=args.ncbi_timeout, backoff=args.ncbi_backoff)
    oai = OpenAI(api_key=openai_key)

    state_path = args.state_file
    processed_path = args.processed_pmids

    processed = load_processed_set(processed_path)
    state = load_state(state_path)

    # Prepare paper source
    pmids_queue: List[str] = []
    history: Optional[PubMedHistory] = None

    if args.pmids:
        pmids_queue = [p.strip() for p in re.split(r"[,\s]+", args.pmids.strip()) if p.strip()]
        total_target = min(len(pmids_queue), args.max_papers)
        eprint(f"[INFO] Using explicit PMIDs (n={len(pmids_queue)}), max_papers={args.max_papers}")
        year_chunks = []  # No year chunking for explicit PMIDs
        base_query = ""
    else:
        if args.query_file:
            base_query = read_text_file(args.query_file)
        elif args.query:
            base_query = args.query.strip()
        else:
            raise SystemExit("Either --pmids, --query_file, or --query must be provided.")
        
        # Check total count
        total_count = pubmed.esearch_count(base_query)
        eprint(f"[INFO] PubMed total hit count: {total_count}")
        
        # Determine if year chunking is needed
        year_chunks = []
        if total_count > NCBI_RETSTART_LIMIT:
            eprint(f"[INFO] Query exceeds NCBI retstart limit ({NCBI_RETSTART_LIMIT}), using year-based chunking...")
            import datetime
            current_year = datetime.datetime.now().year
            # Generate year chunks from newest to oldest
            year_chunks = generate_year_chunks(base_query, 1950, current_year)
            eprint(f"[INFO] Generated {len(year_chunks)} year chunks")
            
            # Restore progress from state
            completed_years = set(state.get("completed_years", []))
            current_chunk_year = state.get("current_chunk_year", None)
            
            # Filter out completed years
            year_chunks = [(q, ys, ye) for q, ys, ye in year_chunks if ye not in completed_years]
            
            # If we were in the middle of a year, start from there
            if current_chunk_year is not None:
                # Find that year's chunk and start from there
                for i, (q, ys, ye) in enumerate(year_chunks):
                    if ye == current_chunk_year:
                        year_chunks = year_chunks[i:]
                        break
            
            if not year_chunks:
                eprint("[INFO] All year chunks already processed.")
                total_target = 0
            else:
                total_target = min(total_count, args.max_papers)
        else:
            # Simple case: no year chunking needed
            history = pubmed.esearch_history(base_query)
            eprint(f"[INFO] PubMed hit count: {history.count}")
            retstart = int(state.get("retstart", 0))
            total_target = min(history.count - retstart, args.max_papers)
            if total_target < 0:
                total_target = 0

    # Counters
    papers_attempted = 0
    papers_with_text = 0
    papers_with_items = 0
    extracted_total_rows = 0

    pbar = tqdm(total=total_target, desc="Mining", unit="paper")

    try:
        # Determine processing mode
        if year_chunks:
            # Year-chunked processing mode
            completed_years = set(state.get("completed_years", []))
            
            for chunk_query, year_start, year_end in year_chunks:
                if pbar.n >= args.max_papers:
                    break
                
                eprint(f"[INFO] Processing year chunk: {year_end}")
                
                # Check if we're resuming this chunk
                if state.get("current_chunk_year") == year_end:
                    retstart = int(state.get("retstart", 0))
                else:
                    retstart = 0
                    state["current_chunk_year"] = year_end
                    state["retstart"] = 0
                    save_state(state_path, state)
                
                # Create history for this chunk
                chunk_history = pubmed.esearch_history(chunk_query)
                eprint(f"[INFO] Year {year_end} has {chunk_history.count} papers (retstart={retstart})")
                
                if chunk_history.count == 0:
                    completed_years.add(year_end)
                    state["completed_years"] = list(completed_years)
                    state["current_chunk_year"] = None
                    state["retstart"] = 0
                    save_state(state_path, state)
                    continue
                
                # Process this chunk
                while retstart < chunk_history.count and pbar.n < args.max_papers:
                    # Check retstart limit
                    if retstart >= NCBI_RETSTART_LIMIT:
                        eprint(f"[WARN] Year {year_end}: retstart ({retstart}) hit limit, marking complete")
                        break
                    
                    batch = pubmed.fetch_id_batch(chunk_history, retstart=retstart, retmax=args.batch_size)
                    retstart += len(batch)
                    state["retstart"] = retstart
                    save_state(state_path, state)
                    
                    if not batch:
                        break
                    
                    safe_sleep(args.ncbi_sleep)
                    
                    # Fetch metadata and abstracts
                    meta = {}
                    abstracts = {}
                    NCBI_FETCH_RETRY = getattr(args, "ncbi_fetch_retries", 6)
                    for attempt in range(1, NCBI_FETCH_RETRY + 1):
                        try:
                            meta = pubmed.esummary(batch)
                            abstracts = pubmed.efetch_abstracts(batch)
                            break
                        except requests.exceptions.ChunkedEncodingError as e:
                            sleep_s = min(60.0, 1.5 * attempt)
                            eprint(f"[WARN] NCBI ChunkedEncodingError (attempt {attempt}/{NCBI_FETCH_RETRY}): {e}. Sleeping {sleep_s:.1f}s...")
                            time.sleep(sleep_s)
                        except requests.exceptions.RequestException as e:
                            sleep_s = min(60.0, 1.5 * attempt)
                            eprint(f"[WARN] NCBI RequestException (attempt {attempt}/{NCBI_FETCH_RETRY}): {e}. Sleeping {sleep_s:.1f}s...")
                            time.sleep(sleep_s)
                    
                    if not abstracts and batch:
                        retstart = max(0, retstart - len(batch))
                        state["retstart"] = retstart
                        save_state(state_path, state)
                        ensure_parent_dir(args.error_log)
                        with open(args.error_log, "a", encoding="utf-8") as f:
                            f.write(f"[NCBI efetch failed] year={year_end}, batch size={len(batch)}\n")
                        time.sleep(5.0)
                        continue
                    
                    safe_sleep(args.ncbi_sleep)
                    
                    for pmid in batch:
                        if pbar.n >= args.max_papers:
                            break
                        if pmid in processed:
                            pbar.update(1)
                            continue
                        
                        papers_attempted += 1
                        title = meta.get(pmid, {}).get("title", "")
                        journal = meta.get(pmid, {}).get("journal", "")
                        doi = meta.get(pmid, {}).get("doi", "")
                        snippet = abstracts.get(pmid, "") or ""
                        
                        if snippet:
                            papers_with_text += 1
                        
                        if not snippet:
                            append_processed(processed_path, pmid)
                            processed.add(pmid)
                            pbar.update(1)
                            continue
                        
                        try:
                            extraction = extract_with_gpt52(
                                client=oai,
                                model=args.model,
                                title=title,
                                journal=journal,
                                doi=doi,
                                snippet=snippet,
                                temperature=args.temperature,
                                max_output_tokens=args.max_output_tokens,
                            )
                        except Exception as ex:
                            ensure_parent_dir(args.error_log)
                            with open(args.error_log, "a", encoding="utf-8") as f:
                                f.write(f"[PMID {pmid}] OpenAI error: {repr(ex)}\n")
                            append_processed(processed_path, pmid)
                            processed.add(pmid)
                            pbar.update(1)
                            continue
                        
                        items = extraction.items if extraction else []
                        if items:
                            papers_with_items += 1
                            extracted_total_rows += len(items)
                            rows = []
                            for it in items:
                                row = it.model_dump()
                                row["reference"] = title or row.get("reference", "")
                                row["journal"] = journal or row.get("journal", "")
                                row["DOI"] = doi or row.get("DOI", "")
                                row["PMID"] = pmid
                                rows.append(row)
                            append_csv_rows(args.out_csv, CSV_HEADER, rows)
                        
                        append_processed(processed_path, pmid)
                        processed.add(pmid)
                        pbar.update(1)
                
                # Mark year as completed
                completed_years.add(year_end)
                state["completed_years"] = list(completed_years)
                state["current_chunk_year"] = None
                state["retstart"] = 0
                save_state(state_path, state)
                eprint(f"[INFO] Completed year {year_end}")
        
        else:
            # Simple processing mode (no year chunking)
            retstart = int(state.get("retstart", 0))
            while pbar.n < total_target:
                if pmids_queue:
                    batch = pmids_queue[: args.batch_size]
                    pmids_queue = pmids_queue[args.batch_size :]
                else:
                    assert history is not None
                    batch = pubmed.fetch_id_batch(history, retstart=retstart, retmax=args.batch_size)
                    retstart += len(batch)
                    state["retstart"] = retstart
                    state["webenv"] = history.webenv
                    state["query_key"] = history.query_key
                    state["count"] = history.count
                    state["query"] = history.query
                    save_state(state_path, state)

                if not batch:
                    break

                safe_sleep(args.ncbi_sleep)

                meta = {}
                abstracts = {}
                NCBI_FETCH_RETRY = getattr(args, "ncbi_fetch_retries", 6)
                for attempt in range(1, NCBI_FETCH_RETRY + 1):
                    try:
                        meta = pubmed.esummary(batch)
                        abstracts = pubmed.efetch_abstracts(batch)
                        break
                    except requests.exceptions.ChunkedEncodingError as e:
                        sleep_s = min(60.0, 1.5 * attempt)
                        eprint(f"[WARN] NCBI ChunkedEncodingError (attempt {attempt}/{NCBI_FETCH_RETRY}): {e}. Sleeping {sleep_s:.1f}s...")
                        time.sleep(sleep_s)
                    except requests.exceptions.RequestException as e:
                        sleep_s = min(60.0, 1.5 * attempt)
                        eprint(f"[WARN] NCBI RequestException (attempt {attempt}/{NCBI_FETCH_RETRY}): {e}. Sleeping {sleep_s:.1f}s...")
                        time.sleep(sleep_s)
                
                if not abstracts and batch:
                    if (not args.pmids) and (history is not None) and (not pmids_queue):
                        retstart = max(0, retstart - len(batch))
                        state["retstart"] = retstart
                        save_state(state_path, state)
                    ensure_parent_dir(args.error_log)
                    with open(args.error_log, "a", encoding="utf-8") as f:
                        f.write(f"[NCBI efetch failed] batch size={len(batch)}\n")
                    time.sleep(5.0)
                    continue
                
                safe_sleep(args.ncbi_sleep)

                for pmid in batch:
                    if pbar.n >= total_target:
                        break

                    if pmid in processed:
                        pbar.update(1)
                        continue

                    papers_attempted += 1
                    title = meta.get(pmid, {}).get("title", "")
                    journal = meta.get(pmid, {}).get("journal", "")
                    doi = meta.get(pmid, {}).get("doi", "")
                    snippet = abstracts.get(pmid, "") or ""

                    if snippet:
                        papers_with_text += 1

                    if not snippet:
                        append_processed(processed_path, pmid)
                        processed.add(pmid)
                        pbar.update(1)
                        continue

                    try:
                        extraction = extract_with_gpt52(
                            client=oai,
                            model=args.model,
                            title=title,
                            journal=journal,
                            doi=doi,
                            snippet=snippet,
                            temperature=args.temperature,
                            max_output_tokens=args.max_output_tokens,
                        )
                    except Exception as ex:
                        ensure_parent_dir(args.error_log)
                        with open(args.error_log, "a", encoding="utf-8") as f:
                            f.write(f"[PMID {pmid}] OpenAI error: {repr(ex)}\n")
                        append_processed(processed_path, pmid)
                        processed.add(pmid)
                        pbar.update(1)
                        continue

                    items = extraction.items if extraction else []
                    if items:
                        papers_with_items += 1
                        extracted_total_rows += len(items)

                        rows = []
                        for it in items:
                            row = it.model_dump()
                            row["reference"] = title or row.get("reference", "")
                            row["journal"] = journal or row.get("journal", "")
                            row["DOI"] = doi or row.get("DOI", "")
                            row["PMID"] = pmid
                            rows.append(row)
                        append_csv_rows(args.out_csv, CSV_HEADER, rows)

                    append_processed(processed_path, pmid)
                    processed.add(pmid)
                    pbar.update(1)

    finally:
        pbar.close()

    print("\nExtraction summary:")
    print(f"  papers_attempted     : {papers_attempted}")
    print(f"  papers_with_text     : {papers_with_text}")
    print(f"  papers_with_items    : {papers_with_items}")
    print(f"  extracted_total_rows : {extracted_total_rows}")
    print(f"  out_csv              : {args.out_csv}")
    print(f"  state_file           : {args.state_file}")
    print(f"  processed_pmids      : {args.processed_pmids}")
    if extracted_total_rows == 0:
        print("  NOTE: 0 rows were extracted. This can happen with small test sizes or query mismatch.")
    return 0


# -----------------------------
# CLI
# -----------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pubmed_projection_miner_gpt52.py")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("mine", help="Search PubMed and extract projection statements into a CSV.")
    # NCBI credentials (compat: --email / --api_key)
    sp.add_argument("--email", dest="email", default="", help="NCBI email (or env NCBI_EMAIL).")
    sp.add_argument("--api_key", dest="api_key", default="", help="NCBI API key (or env NCBI_API_KEY).")
    sp.add_argument("--ncbi_tool", default="pubmed_projection_miner", help="NCBI tool name parameter.")

    # OpenAI key
    sp.add_argument("--openai_api_key", default="", help="OpenAI API key (or env OPENAI_API_KEY).")

    # Data source
    sp.add_argument("--pmids", default="", help="Comma/space-separated PMIDs for a deterministic smoke test.")
    sp.add_argument("--query_file", default="", help="Path to a file containing a PubMed query.")
    sp.add_argument("--query", default="", help="PubMed query string (if not using --query_file).")

    # Run control
    sp.add_argument("--model", default="gpt-5.2", help="Model id (default: gpt-5.2).")
    sp.add_argument("--max_papers", type=int, default=10, help="Maximum number of papers to process.")
    sp.add_argument("--batch_size", type=int, default=20, help="NCBI fetch batch size.")
    sp.add_argument("--ncbi_sleep", type=float, default=0.34, help="Sleep seconds between NCBI calls.")
    sp.add_argument("--ncbi_retries", type=int, default=6, help="NCBI JSON retry count (esearch/esummary).")
    sp.add_argument("--ncbi_timeout", type=int, default=60, help="NCBI HTTP timeout seconds.")
    sp.add_argument("--ncbi_backoff", type=float, default=1.5, help="NCBI retry backoff base seconds.")
    sp.add_argument("--ncbi_fetch_retries", type=int, default=6, help="Retry count for NCBI efetch/esummary transient failures.")
    sp.add_argument("--temperature", type=float, default=0.0, help="LLM temperature.")
    sp.add_argument("--max_output_tokens", type=int, default=1200, help="LLM max output tokens.")

    # Output / resume
    sp.add_argument("--out_csv", default="out_pubmed_utf8.csv", help="Output CSV path.")
    sp.add_argument("--state_file", default="state.json", help="Resume state JSON path.")
    sp.add_argument("--processed_pmids", default="processed_pmids.txt", help="Processed PMID list path.")
    sp.add_argument("--error_log", default="errors.log", help="Error log path (OpenAI failures).")

    sp.set_defaults(func=cmd_mine)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
