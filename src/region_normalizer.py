# -*- coding: utf-8 -*-
"""DHBA / BrainRegion normalizer (optional)

This module tries to map extracted surface-form region names to canonical names/IDs
loaded from your BrainRegion.csv.

Because BrainRegion.csv formats vary, we use heuristics:
- If columns contain something like: id, name, abbreviation, synonym(s), aliases, etc.
- We'll build an alias->canonical mapping and a fuzzy matcher fallback.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^a-z0-9\s\-_/]", "", s)
    return s

@dataclass
class DhbaMatch:
    canonical: str
    dhba_id: str
    score: float

class DhbaNormalizer:
    def __init__(self, alias_to_entry: Dict[str, Tuple[str, str]], canon_list: List[Tuple[str,str]]):
        self.alias_to_entry = alias_to_entry
        self.canon_list = canon_list  # (canonical, id)

    @classmethod
    def from_csv(cls, path: str) -> "DhbaNormalizer":
        alias_to_entry: Dict[str, Tuple[str, str]] = {}
        canon_list: List[Tuple[str,str]] = []
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            cols = [c.lower() for c in (reader.fieldnames or [])]

            # guess columns
            def pick(*cands: str) -> Optional[str]:
                for c in cands:
                    for real in reader.fieldnames or []:
                        if real.lower() == c:
                            return real
                # contains
                for c in cands:
                    for real in reader.fieldnames or []:
                        if c in real.lower():
                            return real
                return None

            col_id = pick("dhbaid","dhba_id","id","regionid","circuit id","circuitid","sid")
            col_name = pick("name","names","region","regionname","canonical","official","dhbaname")
            col_abbr = pick("abbr","abbrev","abbreviation","short","acronym")
            col_syn = pick("synonyms","synonym","aliases","alias","alt","alternative")

            for row in reader:
                dhba_id = (row.get(col_id) or "").strip() if col_id else ""
                canonical = (row.get(col_name) or "").strip() if col_name else ""
                if not canonical:
                    continue
                canon_list.append((canonical, dhba_id))

                aliases = set()
                aliases.add(canonical)
                if col_abbr and row.get(col_abbr):
                    aliases.add(row[col_abbr])
                if col_syn and row.get(col_syn):
                    # split common separators
                    for part in re.split(r"[;|,/]+", row[col_syn]):
                        part = part.strip()
                        if part:
                            aliases.add(part)

                for a in aliases:
                    na = _norm(a)
                    if na:
                        alias_to_entry[na] = (canonical, dhba_id)

        return cls(alias_to_entry=alias_to_entry, canon_list=canon_list)

    def match(self, surface: str, min_score: float = 0.78) -> Optional[DhbaMatch]:
        ns = _norm(surface)
        if not ns:
            return None
        if ns in self.alias_to_entry:
            canonical, dhba_id = self.alias_to_entry[ns]
            return DhbaMatch(canonical=canonical, dhba_id=dhba_id, score=1.0)

        # fuzzy fallback against canon names only
        best = ("", "", 0.0)  # canonical, id, score
        for canonical, dhba_id in self.canon_list:
            sc = SequenceMatcher(None, ns, _norm(canonical)).ratio()
            if sc > best[2]:
                best = (canonical, dhba_id, sc)

        if best[2] >= min_score:
            return DhbaMatch(canonical=best[0], dhba_id=best[1], score=best[2])
        return None
