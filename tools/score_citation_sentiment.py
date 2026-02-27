#!/usr/bin/env python3
"""
Citation Sentiment Index (CSI) Scorer for WholeBIF-RDB
======================================================
Calculates citation sentiment by:
1. Finding citing papers via Semantic Scholar API (free, no auth required for basic use)
2. Extracting citation contexts (the text surrounding where a paper is cited)
3. Analyzing sentiment using Claude API
4. Computing weighted average sentiment score (0.0-1.0)

Score interpretation:
  0.0 - 0.3: Predominantly negative citations (findings disputed/contradicted)
  0.3 - 0.45: Mixed/slightly negative
  0.45 - 0.55: Neutral (factual references without strong sentiment)
  0.55 - 0.7: Mixed/slightly positive
  0.7 - 1.0: Predominantly positive (findings confirmed/extended/praised)

Usage:
  # Full mode with Claude API
  export ANTHROPIC_API_KEY="your-key"
  python score_citation_sentiment.py -i references.csv -c connections.csv -o output.csv

  # Dry-run mode (heuristic scoring, no API needed)
  python score_citation_sentiment.py -i references.csv -c connections.csv -o output.csv --dry-run

  # Score specific references only
  python score_citation_sentiment.py -i references.csv -c connections.csv -o output.csv --refs "Amaral, 1991" "Wei, 2016"

  # With Semantic Scholar API key (higher rate limits)
  export S2_API_KEY="your-s2-key"
  python score_citation_sentiment.py -i references.csv -c connections.csv -o output.csv

Requirements:
  pip install anthropic requests
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import defaultdict
from typing import Optional

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package required. Install with: pip install requests")
    sys.exit(1)


# =============================================================================
# Semantic Scholar API Client
# =============================================================================

class SemanticScholarClient:
    """Client for Semantic Scholar API to fetch citation contexts."""

    BASE_URL = "https://api.semanticscholar.org/graph/v1"

    def __init__(self, api_key: Optional[str] = None):
        self.session = requests.Session()
        self.headers = {}
        if api_key:
            self.headers["x-api-key"] = api_key
        self.session.headers.update(self.headers)
        self._last_request_time = 0
        self._min_interval = 1.0  # 1 second between requests (free tier)

    def _rate_limit(self):
        """Enforce rate limiting."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()

    def get_paper_by_doi(self, doi: str) -> Optional[dict]:
        """Look up a paper by DOI."""
        if not doi:
            return None
        self._rate_limit()
        try:
            url = f"{self.BASE_URL}/paper/DOI:{doi}"
            params = {"fields": "paperId,title,year,citationCount,influentialCitationCount"}
            resp = self.session.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 404:
                return None
            elif resp.status_code == 429:
                print(f"    Rate limited. Waiting 30s...")
                time.sleep(30)
                return self.get_paper_by_doi(doi)
            else:
                print(f"    S2 API error {resp.status_code} for DOI:{doi}")
                return None
        except Exception as e:
            print(f"    S2 API exception for DOI:{doi}: {e}")
            return None

    def get_citations_with_context(self, paper_id: str, limit: int = 50) -> list:
        """Get citing papers with citation contexts."""
        self._rate_limit()
        try:
            url = f"{self.BASE_URL}/paper/{paper_id}/citations"
            params = {
                "fields": "contexts,intents,title,year,citationCount",
                "limit": min(limit, 1000),
            }
            resp = self.session.get(url, params=params, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("data", [])
            elif resp.status_code == 429:
                print(f"    Rate limited. Waiting 30s...")
                time.sleep(30)
                return self.get_citations_with_context(paper_id, limit)
            else:
                print(f"    S2 citations error {resp.status_code} for {paper_id}")
                return []
        except Exception as e:
            print(f"    S2 citations exception: {e}")
            return []


# =============================================================================
# Claude API Sentiment Analyzer
# =============================================================================

class ClaudeSentimentAnalyzer:
    """Uses Claude API to analyze citation sentiment."""

    SYSTEM_PROMPT = """You are an expert in analyzing academic citation sentiment in neuroscience literature.

Given a set of citation contexts (text excerpts where a paper is cited), analyze the overall sentiment:

Scoring guide (0.0 to 1.0):
- 0.0-0.2: Strongly negative (findings contradicted, methods criticized, results not replicated)
- 0.2-0.4: Somewhat negative (limitations noted, partial disagreement, caveats raised)
- 0.4-0.6: Neutral (factual reference, background citation, methodological citation)
- 0.6-0.8: Somewhat positive (findings confirmed, methods adopted, results extended)
- 0.8-1.0: Strongly positive (seminal work, foundational, highly praised, breakthrough)

Consider:
1. Explicit sentiment words (e.g., "elegantly demonstrated", "failed to replicate")
2. Citation intent: background/methodology/result comparison/extension
3. Whether the citing paper builds on or disputes the cited work
4. The overall balance of positive vs negative contexts

Respond with ONLY a JSON object:
{
  "score": <float 0.0-1.0>,
  "positive_count": <int>,
  "neutral_count": <int>,
  "negative_count": <int>,
  "summary": "<one sentence summary of citation reception>"
}"""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        try:
            import anthropic
            self.client = anthropic.Anthropic(api_key=api_key)
        except ImportError:
            print("ERROR: 'anthropic' package required. Install with: pip install anthropic")
            sys.exit(1)
        self.model = model

    def analyze_contexts(self, ref_id: str, title: str, contexts: list[str]) -> dict:
        """Analyze citation contexts for sentiment."""
        if not contexts:
            return {"score": 0.5, "positive_count": 0, "neutral_count": 0,
                    "negative_count": 0, "summary": "No citation contexts available"}

        # Limit contexts to avoid token overflow
        selected = contexts[:30]  # Max 30 contexts
        contexts_text = "\n\n".join(
            f"Context {i+1}: \"{ctx}\""
            for i, ctx in enumerate(selected)
            if ctx and len(ctx.strip()) > 10
        )

        if not contexts_text.strip():
            return {"score": 0.5, "positive_count": 0, "neutral_count": 0,
                    "negative_count": 0, "summary": "No meaningful citation contexts"}

        user_msg = f"""Analyze the citation sentiment for this paper:
Reference: {ref_id}
Title: {title}
Number of citation contexts: {len(selected)} (out of {len(contexts)} total)

Citation contexts:
{contexts_text}

Provide your analysis as JSON."""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=500,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            text = response.content[0].text.strip()
            # Extract JSON from response
            text = re.sub(r"```json\s*", "", text)
            text = re.sub(r"```\s*$", "", text)
            return json.loads(text)
        except json.JSONDecodeError:
            print(f"    Failed to parse Claude response for {ref_id}")
            return {"score": 0.5, "summary": "Parse error"}
        except Exception as e:
            print(f"    Claude API error for {ref_id}: {e}")
            return {"score": 0.5, "summary": f"API error: {e}"}


# =============================================================================
# Heuristic Scorer (for dry-run mode)
# =============================================================================

def heuristic_score(ref_id: str, doi: str, paper_info: Optional[dict]) -> dict:
    """Estimate CSI using heuristics when API is not available."""
    score = 0.5  # Default neutral

    if paper_info:
        citation_count = paper_info.get("citationCount", 0)
        influential_count = paper_info.get("influentialCitationCount", 0)
        year = paper_info.get("year", 2020)

        # High citation count generally indicates positive reception
        if citation_count > 500:
            score += 0.15
        elif citation_count > 200:
            score += 0.10
        elif citation_count > 50:
            score += 0.05
        elif citation_count < 5:
            score -= 0.05

        # Influential citations ratio
        if citation_count > 0:
            inf_ratio = influential_count / citation_count
            if inf_ratio > 0.3:
                score += 0.05
            elif inf_ratio > 0.15:
                score += 0.02

        # Older papers that are still cited tend to be well-regarded
        age = 2025 - year if year else 0
        if age > 20 and citation_count > 100:
            score += 0.05

    # Clamp to valid range
    score = max(0.1, min(0.95, score))

    return {
        "score": round(score, 4),
        "positive_count": 0,
        "neutral_count": 0,
        "negative_count": 0,
        "summary": f"Heuristic estimate (citations: {paper_info.get('citationCount', 'N/A') if paper_info else 'N/A'})",
    }


# =============================================================================
# Main Processing Pipeline
# =============================================================================

def load_references(refs_csv: str) -> dict:
    """Load reference ID -> DOI mapping from references CSV."""
    ref_doi = {}
    with open(refs_csv, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        headers = next(reader)
        for row in reader:
            ref_id = row[0].strip() if len(row) > 0 else ""
            doi = row[3].strip() if len(row) > 3 else ""
            if ref_id:
                ref_doi[ref_id] = doi
    return ref_doi


def load_connections(conn_csv: str) -> tuple:
    """Load connections CSV and identify refs needing CSI scoring."""
    with open(conn_csv, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        headers = next(reader)
        rows = list(reader)

    csi_col = headers.index("Citation sentiment index")
    ref_col = headers.index("Reference ID")

    # Find refs needing scoring
    refs_to_score = set()
    for row in rows:
        ref = row[ref_col].strip()
        csi = row[csi_col].strip()
        if ref and csi in ("0", "0.95", ""):
            refs_to_score.add(ref)

    return headers, rows, csi_col, ref_col, refs_to_score


def process_reference(
    ref_id: str,
    doi: str,
    s2_client: SemanticScholarClient,
    claude_analyzer: Optional[ClaudeSentimentAnalyzer],
    dry_run: bool = False,
) -> dict:
    """Process a single reference to compute CSI."""
    print(f"\n  Processing: {ref_id} (DOI: {doi or 'N/A'})")

    # Step 1: Look up paper on Semantic Scholar
    paper_info = None
    if doi:
        paper_info = s2_client.get_paper_by_doi(doi)
        if paper_info:
            paper_id = paper_info["paperId"]
            title = paper_info.get("title", ref_id)
            cit_count = paper_info.get("citationCount", 0)
            print(f"    Found: '{title}' (citations: {cit_count})")
        else:
            print(f"    Not found on Semantic Scholar")
    else:
        print(f"    No DOI available")

    # Step 2: Get citation contexts
    contexts = []
    intents_summary = defaultdict(int)
    if paper_info:
        citations = s2_client.get_citations_with_context(paper_info["paperId"])
        for cit in citations:
            citing_paper = cit.get("citingPaper", {})
            cit_contexts = cit.get("contexts", []) or []
            cit_intents = cit.get("intents", []) or []
            for ctx in cit_contexts:
                if ctx and len(ctx.strip()) > 10:
                    contexts.append(ctx.strip())
            for intent in cit_intents:
                intents_summary[intent] += 1
        print(f"    Citation contexts found: {len(contexts)}")
        if intents_summary:
            print(f"    Intent distribution: {dict(intents_summary)}")

    # Step 3: Analyze sentiment
    if dry_run or claude_analyzer is None:
        result = heuristic_score(ref_id, doi, paper_info)
        print(f"    Heuristic CSI: {result['score']}")
    else:
        if contexts:
            title = paper_info.get("title", ref_id) if paper_info else ref_id
            result = claude_analyzer.analyze_contexts(ref_id, title, contexts)
            print(f"    Claude CSI: {result['score']} "
                  f"(+{result.get('positive_count',0)} "
                  f"={result.get('neutral_count',0)} "
                  f"-{result.get('negative_count',0)})")
        else:
            # No contexts → use heuristic
            result = heuristic_score(ref_id, doi, paper_info)
            print(f"    Fallback heuristic CSI: {result['score']} (no contexts)")

    result["ref_id"] = ref_id
    result["doi"] = doi
    result["citation_count"] = paper_info.get("citationCount", 0) if paper_info else 0
    result["contexts_found"] = len(contexts)
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Citation Sentiment Index Scorer for WholeBIF-RDB"
    )
    parser.add_argument("-i", "--references", required=True,
                        help="Path to wbReferences CSV")
    parser.add_argument("-c", "--connections", required=True,
                        help="Path to wbConnections CSV")
    parser.add_argument("-o", "--output", required=True,
                        help="Output connections CSV with updated CSI")
    parser.add_argument("--dry-run", action="store_true",
                        help="Use heuristic scoring only (no Claude API)")
    parser.add_argument("--refs", nargs="*",
                        help="Score only specific reference IDs")
    parser.add_argument("--model", default="claude-sonnet-4-20250514",
                        help="Claude model to use")
    parser.add_argument("--max-citations", type=int, default=50,
                        help="Max citing papers to analyze per reference")
    parser.add_argument("--score-all", action="store_true",
                        help="Re-score all refs (not just 0/0.95/empty)")
    parser.add_argument("--log", default=None,
                        help="Path to save detailed scoring log (JSON)")
    args = parser.parse_args()

    print("=" * 60)
    print("Citation Sentiment Index Scorer")
    print("=" * 60)

    # Load data
    print("\n[1/4] Loading data...")
    ref_doi = load_references(args.references)
    print(f"  References loaded: {len(ref_doi)}")

    headers, rows, csi_col, ref_col, refs_to_score = load_connections(args.connections)
    print(f"  Connection rows: {len(rows)}")
    print(f"  Refs needing scoring: {len(refs_to_score)}")

    # Filter to specific refs if requested
    if args.refs:
        refs_to_score = set(args.refs)
        print(f"  Filtered to {len(refs_to_score)} specified refs")

    if args.score_all:
        refs_to_score = set(
            row[ref_col].strip() for row in rows
            if row[ref_col].strip()
        )
        print(f"  Scoring ALL {len(refs_to_score)} refs")

    # Initialize clients
    print("\n[2/4] Initializing API clients...")
    s2_key = os.environ.get("S2_API_KEY")
    s2_client = SemanticScholarClient(api_key=s2_key)
    if s2_key:
        s2_client._min_interval = 0.5  # Higher rate with API key
        print("  Semantic Scholar: API key found (higher rate limits)")
    else:
        print("  Semantic Scholar: No API key (free tier, 1 req/sec)")

    claude_analyzer = None
    if not args.dry_run:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if api_key:
            claude_analyzer = ClaudeSentimentAnalyzer(api_key, model=args.model)
            print(f"  Claude API: Ready (model: {args.model})")
        else:
            print("  Claude API: No ANTHROPIC_API_KEY found → falling back to heuristic")
            args.dry_run = True

    if args.dry_run:
        print("  Mode: Heuristic (dry-run)")

    # Process references
    print(f"\n[3/4] Scoring {len(refs_to_score)} references...")
    scoring_results = {}
    skipped = []

    for i, ref_id in enumerate(sorted(refs_to_score), 1):
        doi = ref_doi.get(ref_id, "")
        if ref_id in ("", "author, year", "#N/A"):
            print(f"\n  [{i}/{len(refs_to_score)}] Skipping invalid ref: '{ref_id}'")
            scoring_results[ref_id] = {
                "score": 0.15, "summary": "Invalid/placeholder reference",
                "ref_id": ref_id, "doi": "", "citation_count": 0, "contexts_found": 0,
            }
            continue

        print(f"\n  [{i}/{len(refs_to_score)}] ", end="")
        result = process_reference(
            ref_id, doi, s2_client, claude_analyzer,
            dry_run=args.dry_run,
        )
        scoring_results[ref_id] = result

    # Apply scores to connections
    print(f"\n[4/4] Applying scores to connections CSV...")
    updated_count = 0
    for row in rows:
        ref = row[ref_col].strip()
        if ref in scoring_results:
            old_csi = row[csi_col].strip()
            new_csi = str(round(scoring_results[ref]["score"], 10))
            row[csi_col] = new_csi
            updated_count += 1

    # Save output
    with open(args.output, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    print(f"  Saved: {args.output}")
    print(f"  Rows updated: {updated_count}")

    # Save log if requested
    if args.log:
        with open(args.log, "w", encoding="utf-8") as f:
            json.dump(scoring_results, f, indent=2, ensure_ascii=False)
        print(f"  Log saved: {args.log}")

    # Summary
    print("\n" + "=" * 60)
    print("Scoring Summary")
    print("=" * 60)
    scores = [r["score"] for r in scoring_results.values()]
    if scores:
        print(f"  References scored: {len(scores)}")
        print(f"  Score range: {min(scores):.4f} - {max(scores):.4f}")
        print(f"  Mean score: {sum(scores)/len(scores):.4f}")

        # Distribution
        brackets = {
            "0.0-0.3 (negative)": 0,
            "0.3-0.45 (mixed-)": 0,
            "0.45-0.55 (neutral)": 0,
            "0.55-0.7 (mixed+)": 0,
            "0.7-1.0 (positive)": 0,
        }
        for s in scores:
            if s < 0.3:
                brackets["0.0-0.3 (negative)"] += 1
            elif s < 0.45:
                brackets["0.3-0.45 (mixed-)"] += 1
            elif s < 0.55:
                brackets["0.45-0.55 (neutral)"] += 1
            elif s < 0.7:
                brackets["0.55-0.7 (mixed+)"] += 1
            else:
                brackets["0.7-1.0 (positive)"] += 1
        for label, count in brackets.items():
            bar = "█" * count
            print(f"    {label}: {count} {bar}")


if __name__ == "__main__":
    main()
