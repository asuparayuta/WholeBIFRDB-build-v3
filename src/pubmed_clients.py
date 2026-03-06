# -*- coding: utf-8 -*-
"""PubMed (NCBI E-utilities) + Europe PMC helpers

We use ONLY official APIs and we respect rate limits.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
EUROPEPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"

@dataclass
class PubMedRecord:
    pmid: str
    title: str
    journal: str
    year: str
    doi: str
    abstract: str

@dataclass
class FullTextResult:
    text: str
    pmcid: str  # may be empty

def _sleep(sec: float):
    if sec > 0:
        time.sleep(sec)

class PubMedClient:
    def __init__(
        self,
        email: str,
        tool: str,
        api_key: Optional[str] = None,
        requests_per_sec: float = 3.0,
        session: Optional[requests.Session] = None,
    ):
        self.email = email
        self.tool = tool
        self.api_key = api_key
        self.session = session or requests.Session()

        # NCBI baseline is 3 rps without key; 10 rps with key.
        # We keep margin by using a slightly slower default.
        if api_key:
            self.min_interval = 1.0 / max(1.0, requests_per_sec)
        else:
            self.min_interval = 1.0 / max(1.0, requests_per_sec)
        self._last_call = 0.0

    def _call(self, endpoint: str, params: Dict[str, Any]) -> requests.Response:
        params = dict(params)
        params["tool"] = self.tool
        params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key

        # rate limit
        now = time.time()
        wait = self.min_interval - (now - self._last_call)
        if wait > 0:
            _sleep(wait)
        self._last_call = time.time()

        url = f"{EUTILS}/{endpoint}"
        r = self.session.get(url, params=params, timeout=60)
        r.raise_for_status()
        return r

    def esearch_history(self, term: str) -> Tuple[int, str, str]:
        """Return (count, webenv, query_key) using usehistory=y and retmax=0."""
        r = self._call("esearch.fcgi", {
            "db": "pubmed",
            "term": term,
            "usehistory": "y",
            "retmax": 0,
            "retmode": "json",
        })
        j = r.json()
        count = int(j["esearchresult"]["count"])
        webenv = j["esearchresult"]["webenv"]
        query_key = j["esearchresult"]["querykey"]
        return count, webenv, query_key

    def esummary_batch(self, webenv: str, query_key: str, retstart: int, retmax: int) -> List[Dict[str, Any]]:
        r = self._call("esummary.fcgi", {
            "db": "pubmed",
            "query_key": query_key,
            "WebEnv": webenv,
            "retstart": retstart,
            "retmax": retmax,
            "retmode": "json",
        })
        j = r.json()
        result = j.get("result", {})
        ids = result.get("uids", [])
        return [result[i] for i in ids if i in result]

    def efetch_abstracts(self, pmids: List[str]) -> Dict[str, PubMedRecord]:
        """Fetch abstracts in one XML call (batch)."""
        r = self._call("efetch.fcgi", {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
        })
        root = ET.fromstring(r.text)
        out: Dict[str, PubMedRecord] = {}

        for art in root.findall(".//PubmedArticle"):
            pmid = (art.findtext(".//MedlineCitation/PMID") or "").strip()
            if not pmid:
                continue

            title = (art.findtext(".//ArticleTitle") or "").strip()
            journal = (art.findtext(".//Journal/Title") or "").strip()

            year = ""
            y = art.findtext(".//JournalIssue/PubDate/Year")
            if y:
                year = y.strip()
            else:
                meddate = art.findtext(".//JournalIssue/PubDate/MedlineDate") or ""
                year = (meddate.strip()[:4] if meddate else "")

            # DOI: try ArticleIdList
            doi = ""
            for aid in art.findall(".//ArticleIdList/ArticleId"):
                if aid.attrib.get("IdType","").lower() == "doi":
                    doi = (aid.text or "").strip()
                    break

            abstract = " ".join((t.text or "").strip() for t in art.findall(".//Abstract/AbstractText") if (t.text or "").strip())
            out[pmid] = PubMedRecord(pmid=pmid, title=title, journal=journal, year=year, doi=doi, abstract=abstract)

        return out

class EuropePMCClient:
    def __init__(self, session: Optional[requests.Session] = None, min_interval: float = 0.2):
        self.session = session or requests.Session()
        self.min_interval = min_interval
        self._last_call = 0.0

    def _call(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        now = time.time()
        wait = self.min_interval - (now - self._last_call)
        if wait > 0:
            _sleep(wait)
        self._last_call = time.time()

        url = f"{EUROPEPMC}/{path.lstrip('/')}"
        r = self.session.get(url, params=params, timeout=60)
        r.raise_for_status()
        return r.json()

    def fetch_fulltext_by_pmid(self, pmid: str) -> FullTextResult:
        """Try to get fulltext from Europe PMC if available (typically via PMCID)."""
        q = f"EXT_ID:{pmid} AND SRC:MED"
        j = self._call("search", {"query": q, "format": "json", "pageSize": 1})
        hits = (j.get("resultList", {}) or {}).get("result", []) or []
        if not hits:
            return FullTextResult(text="", pmcid="")

        hit = hits[0]
        pmcid = hit.get("pmcid", "") or ""

        # Prefer the XML full text endpoint if PMCID exists
        if pmcid:
            try:
                xml = self.session.get(f"{EUROPEPMC}/{pmcid}/fullTextXML", timeout=60)
                if xml.status_code == 200 and xml.text.strip().startswith("<"):
                    txt = _strip_xml_to_text(xml.text)
                    return FullTextResult(text=txt, pmcid=pmcid)
            except Exception:
                pass

        return FullTextResult(text="", pmcid=pmcid)

    def cited_by_count(self, pmid: str) -> Optional[int]:
        q = f"EXT_ID:{pmid} AND SRC:MED"
        j = self._call("search", {"query": q, "format": "json", "pageSize": 1})
        hits = (j.get("resultList", {}) or {}).get("result", []) or []
        if not hits:
            return None
        val = hits[0].get("citedByCount")
        try:
            return int(val)
        except Exception:
            return None

def _strip_xml_to_text(xml_text: str) -> str:
    """Very lightweight XML->text for JATS-like fullTextXML."""
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return ""
    # collect text from common tags
    parts: List[str] = []
    for elem in root.iter():
        if elem.tag.lower().endswith(("title","p","caption")):
            t = (elem.text or "").strip()
            if t:
                parts.append(t)
    return "\n".join(parts)
