"""
credibility_calculator.py — Credibility Score Computation Engine
=================================================================

This module implements the credibility scoring logic for the WholeBIF-RDB
data ingestion pipeline. It corresponds to the "Credibility Calculation"
box in the pipeline architecture diagram.

Three scores are computed here:

  1. PDER (Projection Direction Evaluation Rating)
     Evaluates how reliably a measurement method can determine the
     directionality of a neural projection. Anterograde/retrograde tracers
     score highest (~0.85-0.90) because they directly reveal projection
     direction, while fMRI scores lower (~0.40) because functional
     connectivity does not inherently distinguish direction.

  2. CSI (Citation Sentiment Index)
     Evaluates how the scientific community has received a paper, based
     on how it is cited by subsequent publications. A highly-cited paper
     with predominantly positive citations gets a high CSI; a paper that
     has been criticized or retracted gets a low CSI.

  3. CR (Credibility Rating)
     The final credibility score, computed as the product of all 6
     component scores:

       CR = Source Region Score × Receiver Region Score × CSI
            × Literature Type Score × Taxon Score × PDER

     This multiplicative formula means that any single score of 0
     drives the entire CR to 0, reflecting the principle that a fatal
     weakness in any dimension makes the entire record unreliable.

Operating Modes:
  - Heuristic mode (use_api=False): Uses a rule-based lookup table for
    PDER and a cache + year-based heuristic for CSI. Fast, deterministic,
    requires no API keys. Used in testing and offline operation.

  - API mode (use_api=True): Uses the Claude API for PDER scoring and
    the Semantic Scholar API for CSI. Higher accuracy but requires network
    access and API keys. Used in production.

    When the API call fails, both methods gracefully fall back to the
    heuristic, so the pipeline never crashes due to API issues.
"""

import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)


class CredibilityCalculator:
    """
    Central class for computing credibility scores.

    Instantiate with use_api=False for testing/offline, or use_api=True
    with an ANTHROPIC_API_KEY environment variable for production scoring.

    Example usage:
        calc = CredibilityCalculator(use_api=False)
        pder = calc.score_pder("Tracer study", "Experimental results")
        csi = calc.score_csi("Amaral, 1991", "10.1002/hipo.450010410")
        cr = calc.compute_cr(1.0, 1.0, csi, 0.8, 0.5, pder)
    """

    def __init__(self, use_api: bool = False, api_key: Optional[str] = None):
        """
        Args:
            use_api:  If True, attempt to use Claude API / Semantic Scholar API.
                      Falls back to heuristic on failure.
            api_key:  Anthropic API key. If not provided, reads from the
                      ANTHROPIC_API_KEY environment variable.
        """
        self.use_api = use_api
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._claude_client = None  # Lazily initialized on first API call

    # ====================================================================
    # PDER (Method Score) — Rule-Based Lookup Table
    # ====================================================================
    #
    # This table maps substrings found in the "Measurement method" field
    # to PDER scores. The matching is case-insensitive and uses substring
    # containment (not exact match), so "anterograde tracer (BDA)" will
    # match the "anterograde" entry.
    #
    # Score ranges by category:
    #   0.80 - 0.95 : Tracing methods (direct proof of projection direction)
    #   0.55 - 0.75 : Electrophysiology / optogenetics (indirect direction inference)
    #   0.30 - 0.55 : Imaging methods (connectivity observed, direction ambiguous)
    #   0.15 - 0.40 : Secondary sources (reviews, textbooks, hypotheses)
    #
    # The ordering of entries matters: more specific patterns should appear
    # before broader ones to avoid false matches. For example, "resting-state"
    # (0.40) should be checked before a hypothetical "state" pattern.

    PDER_RULES: dict[str, float] = {
        # ------ Tracing methods (0.80 - 0.95) ------
        # These directly label neurons or axons to reveal projection paths.
        # They provide the strongest evidence for directionality.
        "various tracing": 0.90,       # Multiple tracing techniques combined
        "tracer study": 0.85,          # Generic tracer study
        "anterograde": 0.90,           # Anterograde tracers (BDA, PHA-L, etc.)
        "retrograde": 0.90,            # Retrograde tracers (FG, CTB, etc.)
        "trans-synaptic": 0.90,        # Trans-synaptic viral tracers (PRV, rabies)
        "viral tracing": 0.85,         # Viral vector-based tracing (AAV, etc.)
        "pha-l": 0.90,                 # Phaseolus vulgaris leucoagglutinin
        "brdu": 0.80,                  # Bromodeoxyuridine (birth-dating, lower directional info)
        "hrp": 0.85,                   # Horseradish peroxidase (classic tracer)
        "biocytin": 0.85,              # Intracellular fill revealing axonal morphology
        "fluorogold": 0.85,            # Retrograde fluorescent tracer
        "ctb": 0.85,                   # Cholera toxin subunit B (retrograde tracer)
        "dii": 0.80,                   # Carbocyanine dye (works in fixed tissue)
        "wheat germ agglutinin": 0.85, # WGA conjugated tracer
        "autoradiograph": 0.85,        # Autoradiographic tracing (tritiated amino acids)

        # ------ Electrophysiology (0.55 - 0.75) ------
        # These infer direction from stimulus-response relationships.
        # Strong evidence but less direct than anatomical tracers.
        "electrophys": 0.65,           # Generic electrophysiology
        "electrophysiol": 0.65,        # Alternate spelling in some records
        "intracellular recording": 0.65,  # Sharp electrode or whole-cell recording
        "patch clamp": 0.65,           # Patch-clamp recording (high resolution)
        "extracellular recording": 0.60,  # Field or single-unit recording
        "multi-electrode": 0.60,       # Multi-electrode array
        "single-unit": 0.60,           # Single-unit recording
        "local field potential": 0.55, # LFP — population-level, less directional info

        # ------ Optogenetics / Chemogenetics (0.55 - 0.75) ------
        # Genetically targeted manipulation of specific neuron populations.
        # Direction can be inferred from which population is activated/silenced.
        "opto/chemo": 0.65,            # Combined optogenetic/chemogenetic approach
        "optogenet": 0.65,             # Optogenetics (ChR2, NpHR, etc.)
        "chemogenet": 0.60,            # Chemogenetics (DREADDs)
        "dreadd": 0.60,                # Designer Receptors Exclusively Activated by Designer Drugs
        "channelrhodopsin": 0.65,      # ChR2-assisted circuit mapping (CRACM)

        # ------ Anatomical / Structural imaging (0.55 - 0.70) ------
        # High-resolution structural methods that reveal physical connections.
        "anatomical imaging": 0.55,    # Generic anatomical imaging
        "clearing": 0.55,              # Tissue clearing (CLARITY, iDISCO, etc.)
        "light sheet": 0.55,           # Light-sheet fluorescence microscopy
        "electron microscop": 0.70,    # Electron microscopy (synaptic-level resolution)
        "confocal": 0.60,              # Confocal microscopy

        # ------ Functional imaging (0.30 - 0.50) ------
        # These detect correlated activity between regions but cannot
        # determine which region is projecting to which. This inherent
        # limitation of functional imaging is reflected in the lower scores.
        "dti": 0.45,                   # Diffusion Tensor Imaging
        "tractograph": 0.45,           # DTI tractography
        "diffusion tensor": 0.45,      # Alternate DTI phrasing
        "resting-state": 0.40,         # Resting-state fMRI
        "resting state": 0.40,         # Alternate phrasing (no hyphen)
        "functional magnetic resonance": 0.40,  # Full fMRI name
        "fmri": 0.40,                  # fMRI abbreviation
        "functional connectivity": 0.40,  # Generic functional connectivity
        "bold": 0.40,                  # Blood-oxygen-level-dependent signal
        "pet": 0.40,                   # Positron Emission Tomography
        "eeg": 0.35,                   # Electroencephalography (very low spatial resolution)
        "meg": 0.35,                   # Magnetoencephalography

        # ------ Secondary sources (0.15 - 0.40) ------
        # These do not report original experimental data.
        # A review citing tracer studies is less reliable than the
        # original tracer study itself, because of potential
        # misinterpretation or oversimplification.
        "review": 0.30,                # Review paper
        "textbook": 0.25,              # Textbook reference
        "unspecified": 0.30,           # Method not specified in the record
        "data description": 0.25,      # Descriptive account without methodology
        "hypothesis": 0.15,            # Hypothetical connection (not verified)
        "insight": 0.15,               # Perspective / opinion piece
    }

    def score_pder(self, measurement_method: str, literature_type: str = "") -> float:
        """
        Compute the PDER score for a given measurement method.

        The literature_type parameter provides context: the same method
        string (e.g., "Tracer study") should score lower when it appears
        in a review paper than in an original experimental paper, because
        a review merely references the tracing result rather than performing
        it directly.

        Args:
            measurement_method: Free-text method description from the record.
                                Examples: "Tracer study", "fMRI",
                                "anterograde tracer (BDA)", "Review"
            literature_type:    Optional. The literature type of the source
                                paper (e.g., "Review", "Experimental results").
                                Used to apply a context-dependent discount.

        Returns:
            A float in [0.0, 1.0]. Returns 0.0 for empty/None input.
        """
        if self.use_api and self.api_key:
            return self._score_pder_api(measurement_method, literature_type)
        return self._score_pder_heuristic(measurement_method, literature_type)

    def _score_pder_heuristic(self, method: str, lit_type: str = "") -> float:
        """
        Rule-based PDER scoring using the PDER_RULES lookup table.

        Matching logic:
          1. If method is empty or None, return 0.0 immediately.
          2. Convert method to lowercase and search for substring matches
             against the PDER_RULES keys.
          3. If a match is found AND the literature type indicates a review,
             apply a 25% discount to tracing-tier scores (>= 0.80).
             This reflects the reduced reliability of secondhand reporting.
          4. If no rule matches, try fallback keyword heuristics:
             - Anatomical technique keywords (stain, nissl, etc.) → 0.55
             - Connectivity keywords (connect, circuit, etc.) → 0.40
          5. If nothing matches at all, return 0.30 (default for unrecognized).
        """
        if not method or method.strip() == "":
            return 0.0

        method_lower = method.strip().lower()

        # Try each rule in the lookup table (substring match)
        for pattern, score in self.PDER_RULES.items():
            if pattern in method_lower:
                # Context adjustment: if this record comes from a review paper
                # and the matched method is in the tracing tier (>= 0.80),
                # discount the score because reviews report others' experiments.
                # Example: "Tracer study" in a review → 0.85 * 0.75 ≈ 0.64
                if lit_type and "review" in lit_type.lower():
                    if score >= 0.80:
                        return score * 0.75
                return score

        # Fallback: anatomical technique keywords not in the main table
        if any(kw in method_lower for kw in ["stain", "nissl", "golgi", "immuno"]):
            return 0.55

        # Fallback: generic connectivity-related keywords
        if any(kw in method_lower for kw in ["connect", "circuit", "pathway"]):
            return 0.40

        # Final fallback: unrecognized method name
        return 0.30

    def _score_pder_api(self, method: str, lit_type: str = "") -> float:
        """
        Claude API-based PDER scoring for higher accuracy.

        Sends the method string and literature type to Claude with a
        system prompt asking for a neuroscience expert evaluation.
        The response is expected as JSON: {"score": 0.XX, "reason": "..."}.

        On any failure (network error, parse error, etc.), gracefully
        falls back to the heuristic method.
        """
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
            # Parse the JSON response, stripping any markdown code fences
            text = response.content[0].text.strip()
            text = re.sub(r"```json\s*", "", text)
            text = re.sub(r"```\s*$", "", text)
            import json
            result = json.loads(text)
            return float(result["score"])
        except Exception as e:
            logger.warning(f"PDER API error for '{method}': {e}, falling back to heuristic")
            return self._score_pder_heuristic(method, lit_type)

    # ====================================================================
    # CSI (Citation Sentiment Index) — Cache + Heuristic + API
    # ====================================================================
    #
    # CSI scoring has three tiers:
    #   1. Cache lookup: If the reference is in KNOWN_CSI, return immediately.
    #      These are landmark papers whose citation profiles have been manually
    #      verified. Currently 16 papers are cached.
    #   2. API lookup: Query Semantic Scholar for citation count and
    #      influential citation count, then estimate sentiment.
    #   3. Heuristic: For papers not in cache and when API is unavailable,
    #      estimate CSI based on the publication year. Older papers that are
    #      still being referenced are likely well-regarded; very new papers
    #      have insufficient citation data for meaningful assessment.

    KNOWN_CSI: dict[str, float] = {
        # Landmark neuroscience papers with manually verified citation profiles.
        # Scores were determined by analyzing citation contexts through
        # Semantic Scholar and Claude sentiment analysis.
        #
        # Format: "Author, Year": CSI score
        "Amaral, 1991": 0.85,      # Hippocampal anatomy (seminal, 443+ citations)
        "De Zeeuw, 2021": 0.82,    # Cerebellar circuits (Nature Neuroscience)
        "Economo, 2018": 0.82,     # Motor cortex cell types (Nature)
        "Ito, 1977": 0.82,         # Cerebellar physiology (classic)
        "Markov, 2013": 0.82,      # Cortical connectivity atlas
        "Munoz, 1993": 0.80,       # Superior colliculus (classic)
        "Pitkänen, 2000": 0.80,    # Amygdala connectivity (200 rows in WholeBIF)
        "McNaughton, 1977": 0.78,  # Hippocampal physiology
        "Harris, 2015": 0.78,      # Hippocampal place cells
        "Kohara, 2013": 0.78,      # Hippocampal circuit dissection
        "Romanski, 2009": 0.78,    # Prefrontal connectivity (62 rows in WholeBIF)
        "Shepherd, 2013": 0.78,    # Cortical microcircuit review (Nat Rev Neurosci)
        "Witter, 2000": 0.78,      # Entorhinal cortex connectivity
        "Wei, 2016": 0.76,         # Basal ganglia optogenetics (Neuron)
        "Hikosaka, 2007": 0.75,    # Basal ganglia reward circuits
        "Moser, 2010": 0.75,       # Grid cells and spatial navigation
    }

    def score_csi(self, reference_id: str, doi: str = "") -> float:
        """
        Compute the Citation Sentiment Index for a reference.

        Lookup order:
          1. KNOWN_CSI cache (immediate return if found)
          2. Semantic Scholar API (if use_api=True and DOI is available)
          3. Year-based heuristic fallback

        Args:
            reference_id: Citation in "Author, YYYY" format.
            doi:          DOI string for Semantic Scholar lookup.
                          May be empty for older papers without DOIs.

        Returns:
            A float in [0.0, 1.0].
        """
        # Tier 1: Check the manually verified cache first
        if reference_id in self.KNOWN_CSI:
            return self.KNOWN_CSI[reference_id]

        # Tier 2: API lookup (requires both API mode and a valid DOI)
        if self.use_api and self.api_key and doi:
            return self._score_csi_api(reference_id, doi)

        # Tier 3: Heuristic based on publication year
        return self._score_csi_heuristic(reference_id)

    def _score_csi_heuristic(self, reference_id: str) -> float:
        """
        Estimate CSI based on the publication year extracted from the reference ID.

        Assumptions:
          - "author, year" and "#N/A" are placeholder values from the spreadsheet
            and receive a very low score (0.15) since they represent data errors.
          - Papers from 2024 onward are too new to have meaningful citation data,
            so they get a neutral score (0.50).
          - Papers from 2015-2023 that appear in the database are assumed to be
            reasonably well-cited, getting a slightly positive score (0.55).
          - Papers from before 2000 that are still referenced in active research
            are likely well-established, getting a moderately positive score (0.60).

        These heuristics are deliberately conservative. The API mode should be
        used for production scoring where accuracy matters.
        """
        # Handle known placeholder/error values
        if not reference_id or reference_id in ("author, year", "#N/A"):
            return 0.15

        # Try to extract the publication year from "Author, YYYY"
        match = re.search(r'(\d{4})$', reference_id.strip())
        if match:
            year = int(match.group(1))
            if year >= 2024:
                return 0.50  # Too new — insufficient citation data
            if year >= 2015:
                return 0.55  # Recent but established
            if year < 2000:
                return 0.60  # Classic paper still in active use

        return 0.55  # Default: neutral-positive

    def _score_csi_api(self, reference_id: str, doi: str) -> float:
        """
        Estimate CSI using the Semantic Scholar API.

        Queries the paper's citation count and influential citation count,
        then computes a score based on these metrics:
          - Base score: 0.50 (neutral)
          - 500+ citations: +0.15
          - 200+ citations: +0.10
          - 50+ citations:  +0.05
          - <5 citations:   -0.05
          - High influential citation ratio (>30%): +0.05

        The final score is clamped to [0.10, 0.95].

        On any failure, falls back to the heuristic method.
        """
        try:
            import requests
            resp = requests.get(
                f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}",
                params={"fields": "citationCount,influentialCitationCount"},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                cit_count = data.get("citationCount", 0)
                inf_count = data.get("influentialCitationCount", 0)

                # Start from neutral and adjust based on citation metrics
                score = 0.50
                if cit_count > 500:
                    score += 0.15
                elif cit_count > 200:
                    score += 0.10
                elif cit_count > 50:
                    score += 0.05
                elif cit_count < 5:
                    score -= 0.05

                # Bonus for high influential citation ratio
                # (citations that significantly build on the paper's findings)
                if cit_count > 0:
                    inf_ratio = inf_count / cit_count
                    if inf_ratio > 0.3:
                        score += 0.05

                return max(0.1, min(0.95, score))

            # Non-200 response: fall back to heuristic
            return self._score_csi_heuristic(reference_id)

        except Exception as e:
            logger.warning(f"CSI API error for '{reference_id}': {e}")
            return self._score_csi_heuristic(reference_id)

    # ====================================================================
    # CR (Credibility Rating) — Product of All Six Scores
    # ====================================================================

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
        Compute the Credibility Rating as the product of all 6 component scores.

        CR = Source Region × Receiver Region × CSI × Lit Type × Taxon × PDER

        Important mathematical properties verified by tests:
          - If all scores are 1.0, CR = 1.0 (maximum credibility)
          - If any score is 0.0, CR = 0.0 (zero propagation)
          - Swapping source_region and receiver_region does not change CR
            (commutativity of multiplication)
          - Increasing any score increases CR (monotonicity)

        The result is rounded to 4 decimal places to avoid floating-point
        artifacts while preserving sufficient precision for comparison.

        Args:
            source_region:  Accuracy of sender region identification [0-1]
            receiver_region: Accuracy of receiver region identification [0-1]
            csi:            Citation Sentiment Index [0-1]
            literature_type: Score based on publication type [0-1]
            taxon:          Species relevance score [0-1]
            pder:           Method directional accuracy score [0-1]

        Returns:
            CR value in [0.0, 1.0], rounded to 4 decimal places.
        """
        cr = source_region * receiver_region * csi * literature_type * taxon * pder
        return round(cr, 4)

    # ====================================================================
    # Internal Utilities
    # ====================================================================

    def _get_claude_client(self):
        """
        Lazily initialize and return the Anthropic API client.

        The client is created on first use rather than at __init__ time,
        so that heuristic-only usage doesn't require the anthropic package
        to be installed.
        """
        if self._claude_client is None:
            import anthropic
            self._claude_client = anthropic.Anthropic(api_key=self.api_key)
        return self._claude_client
