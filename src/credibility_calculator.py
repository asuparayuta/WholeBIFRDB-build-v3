"""
credibility_calculator.py
============================
信頼度計算モジュール。

パイプライン図の「信頼度計算」ボックスに対応。

計算対象:
  1. Method Score (PDER): 手法の方向性評価
  2. Citation Sentiment Index (CSI): 引用感情指標
  3. Credibility Rating (CR): 6スコアの積

CR = Source Region Score × Receiver Region Score × CSI
     × Literature Type Score × Taxon Score × PDER
"""

import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)


class CredibilityCalculator:
    """
    Calculates credibility scores for WholeBIF-RDB records.

    Modes:
      - use_api=True:  Claude API で PDER/CSI を計算（高精度）
      - use_api=False: ルールベースのヒューリスティック（テスト用・オフライン用）
    """

    def __init__(self, use_api: bool = False, api_key: Optional[str] = None):
        self.use_api = use_api
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._claude_client = None

    # ================================================================
    # PDER (Method Score) Calculation
    # ================================================================

    # Rule-based PDER lookup table
    PDER_RULES: dict[str, float] = {
        # Tracing methods (highest)
        "various tracing": 0.90,
        "tracer study": 0.85,
        "anterograde": 0.90,
        "retrograde": 0.90,
        "trans-synaptic": 0.90,
        "viral tracing": 0.85,
        "pha-l": 0.90,
        "brdu": 0.80,
        "hrp": 0.85,
        "biocytin": 0.85,
        "fluorogold": 0.85,
        "ctb": 0.85,
        "dii": 0.80,
        "wheat germ agglutinin": 0.85,
        "autoradiograph": 0.85,
        # Electrophysiology
        "electrophys": 0.65,
        "electrophysiol": 0.65,
        "intracellular recording": 0.65,
        "patch clamp": 0.65,
        "extracellular recording": 0.60,
        "multi-electrode": 0.60,
        "single-unit": 0.60,
        "local field potential": 0.55,
        # Opto/Chemo
        "opto/chemo": 0.65,
        "optogenet": 0.65,
        "chemogenet": 0.60,
        "dreadd": 0.60,
        "channelrhodopsin": 0.65,
        # Imaging methods
        "anatomical imaging": 0.55,
        "clearing": 0.55,
        "light sheet": 0.55,
        "electron microscop": 0.70,
        "confocal": 0.60,
        # Functional imaging (lower due to direction ambiguity)
        "dti": 0.45,
        "tractograph": 0.45,
        "diffusion tensor": 0.45,
        "resting-state": 0.40,
        "resting state": 0.40,
        "functional magnetic resonance": 0.40,
        "fmri": 0.40,
        "functional connectivity": 0.40,
        "bold": 0.40,
        "pet": 0.40,
        "eeg": 0.35,
        "meg": 0.35,
        # Secondary sources
        "review": 0.30,
        "textbook": 0.25,
        "unspecified": 0.30,
        "data description": 0.25,
        "hypothesis": 0.15,
        "insight": 0.15,
    }

    def score_pder(self, measurement_method: str, literature_type: str = "") -> float:
        """
        Compute Method Score (PDER) for a measurement method.

        Args:
            measurement_method: The method string (e.g., "Tracer study", "fMRI")
            literature_type: Optional literature type for context

        Returns:
            PDER score [0.0, 1.0]
        """
        if self.use_api and self.api_key:
            return self._score_pder_api(measurement_method, literature_type)
        return self._score_pder_heuristic(measurement_method, literature_type)

    def _score_pder_heuristic(self, method: str, lit_type: str = "") -> float:
        """Rule-based PDER scoring."""
        if not method or method.strip() == "":
            return 0.0

        method_lower = method.strip().lower()

        # Direct lookup
        for pattern, score in self.PDER_RULES.items():
            if pattern in method_lower:
                # Adjust for review papers that reference tracing
                if lit_type and "review" in lit_type.lower():
                    if score >= 0.80:
                        return score * 0.75  # Reviews of tracing → ~0.65
                return score

        # Fallback: if it mentions any anatomical technique
        if any(kw in method_lower for kw in ["stain", "nissl", "golgi", "immuno"]):
            return 0.55

        # Fallback: if it mentions any connectivity
        if any(kw in method_lower for kw in ["connect", "circuit", "pathway"]):
            return 0.40

        return 0.30  # default for unrecognized methods

    def _score_pder_api(self, method: str, lit_type: str = "") -> float:
        """Claude API-based PDER scoring."""
        try:
            client = self._get_claude_client()
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=200,
                system=(
                    "You are a neuroscience expert evaluating measurement methods for "
                    "their ability to determine projection directionality. "
                    "Rate 0.0-1.0. Return ONLY a JSON: {\"score\": 0.XX, \"reason\": \"...\"}"
                ),
                messages=[{
                    "role": "user",
                    "content": f"Method: {method}\nLiterature type: {lit_type}\nRate PDER score:",
                }],
            )
            text = response.content[0].text.strip()
            text = re.sub(r"```json\s*", "", text)
            text = re.sub(r"```\s*$", "", text)
            import json
            result = json.loads(text)
            return float(result["score"])
        except Exception as e:
            logger.warning(f"PDER API error for '{method}': {e}, using heuristic")
            return self._score_pder_heuristic(method, lit_type)

    # ================================================================
    # CSI (Citation Sentiment Index) Calculation
    # ================================================================

    # Known CSI scores from previous analysis
    KNOWN_CSI: dict[str, float] = {
        "Amaral, 1991": 0.85,
        "De Zeeuw, 2021": 0.82,
        "Economo, 2018": 0.82,
        "Ito, 1977": 0.82,
        "Markov, 2013": 0.82,
        "Munoz, 1993": 0.80,
        "Pitkänen, 2000": 0.80,
        "McNaughton, 1977": 0.78,
        "Harris, 2015": 0.78,
        "Kohara, 2013": 0.78,
        "Romanski, 2009": 0.78,
        "Shepherd, 2013": 0.78,
        "Witter, 2000": 0.78,
        "Wei, 2016": 0.76,
        "Hikosaka, 2007": 0.75,
        "Moser, 2010": 0.75,
    }

    def score_csi(self, reference_id: str, doi: str = "") -> float:
        """
        Compute Citation Sentiment Index for a reference.

        Args:
            reference_id: e.g., "Amaral, 1991"
            doi: DOI string for API lookup

        Returns:
            CSI score [0.0, 1.0]
        """
        # Check cache first
        if reference_id in self.KNOWN_CSI:
            return self.KNOWN_CSI[reference_id]

        if self.use_api and self.api_key and doi:
            return self._score_csi_api(reference_id, doi)
        return self._score_csi_heuristic(reference_id)

    def _score_csi_heuristic(self, reference_id: str) -> float:
        """Heuristic CSI: default to 0.5 (neutral) for unknown papers."""
        if not reference_id or reference_id in ("author, year", "#N/A"):
            return 0.15

        # Extract year
        match = re.search(r'(\d{4})$', reference_id.strip())
        if match:
            year = int(match.group(1))
            # Very new papers: neutral (not enough citations yet)
            if year >= 2024:
                return 0.50
            # Recent papers: slightly positive default
            if year >= 2015:
                return 0.55
            # Older papers that are still referenced: likely positive
            if year < 2000:
                return 0.60
        return 0.55  # default neutral-positive

    def _score_csi_api(self, reference_id: str, doi: str) -> float:
        """Semantic Scholar + Claude API-based CSI."""
        try:
            import requests
            # Lookup on Semantic Scholar
            resp = requests.get(
                f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}",
                params={"fields": "citationCount,influentialCitationCount"},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                cit_count = data.get("citationCount", 0)
                inf_count = data.get("influentialCitationCount", 0)

                # Simple heuristic from citation metrics
                score = 0.50
                if cit_count > 500:
                    score += 0.15
                elif cit_count > 200:
                    score += 0.10
                elif cit_count > 50:
                    score += 0.05
                elif cit_count < 5:
                    score -= 0.05

                if cit_count > 0:
                    inf_ratio = inf_count / cit_count
                    if inf_ratio > 0.3:
                        score += 0.05

                return max(0.1, min(0.95, score))

            return self._score_csi_heuristic(reference_id)

        except Exception as e:
            logger.warning(f"CSI API error for '{reference_id}': {e}")
            return self._score_csi_heuristic(reference_id)

    # ================================================================
    # CR (Credibility Rating) Calculation
    # ================================================================

    @staticmethod
    def compute_cr(
        source_region: float,
        receiver_region: float,
        csi: float,
        literature_type: float,
        taxon: float,
        pder: float,
    ) -> float:
        """
        Compute Credibility Rating as product of all 6 scores.

        CR = Source Region × Receiver Region × CSI × Lit Type × Taxon × PDER

        Returns:
            CR value (may be 0 if any component is 0)
        """
        cr = source_region * receiver_region * csi * literature_type * taxon * pder
        return round(cr, 4)

    # ================================================================
    # Utilities
    # ================================================================

    def _get_claude_client(self):
        """Lazy-load Claude API client."""
        if self._claude_client is None:
            import anthropic
            self._claude_client = anthropic.Anthropic(api_key=self.api_key)
        return self._claude_client
