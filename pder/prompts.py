"""
prompts.py
==========
Neural Projection Scoring Pipeline — Complete Prompt Definitions
All three stages are defined here as plain string constants.

Stage 1 : Paper summarization
Stage 2 : Experimental method extraction
Stage 3 : Evidence-grounded directionality scoring

This file is imported by every stage script and the orchestrator.
"""


# ==========================================================================
#  STAGE 1 — PAPER SUMMARIZATION
# ==========================================================================
#
#  Input  : title + abstract (+ full text if available)
#  Output : structured JSON summarising the paper's core content,
#           species, brain regions, and experimental approach
# ==========================================================================

STAGE1_SYSTEM = """\
You are a neuroscience literature analyst.
Your task is to produce a concise, structured summary of a neuroscience paper
that focuses on neural projection mapping, brain connectivity, or white matter
tract tracing.

Output ONLY a valid JSON object — no preamble, no markdown fences.
"""

STAGE1_USER_TEMPLATE = """\
Summarize the following paper. Extract the key information needed to evaluate
what experimental method was used and how it was used to study neural projections.

=== PAPER ===
PubMed ID : {pubmed_id}
Title     : {title}
Abstract  : {abstract}
Full text excerpt (if available):
{fulltext}
=============

Return a JSON object with EXACTLY this structure:
{{
  "pubmed_id": "{pubmed_id}",
  "title": "<string>",
  "year": <integer or null>,
  "journal": "<string or null>",
  "species": "<one of: human | macaque | mouse | rat | other_animal | mixed | unknown>",
  "brain_regions": ["<region1>", "<region2>"],
  "key_finding": "<one sentence — what projection or connectivity was demonstrated>",
  "summary": "<3-5 sentence summary focused on method and finding>",
  "uses_neural_projection_tracing": <true or false>,
  "data_quality_notes": "<any caveats about study design, sample size, or method reliability>"
}}
"""


# ==========================================================================
#  STAGE 2 — EXPERIMENTAL METHOD EXTRACTION
# ==========================================================================
#
#  Input  : Stage 1 summary JSON (per paper)
#  Output : list of methods used in that paper, with directionality details
# ==========================================================================

STAGE2_SYSTEM = """\
You are an expert neuroanatomist and neuroscience methods specialist.

Your task is to extract the experimental methods used to study neural projections
from a summarised neuroscience paper record.

For each method identified, you must specify:
  - The standardised method name and category
  - Whether and how the method establishes directionality (source → target)
  - The species and whether the method was applied to human brain tissue

Output ONLY a valid JSON object — no preamble, no markdown fences.
"""

STAGE2_USER_TEMPLATE = """\
The following is a structured summary of a neuroscience paper.
Extract all experimental methods used to study neural projections or connectivity.

=== PAPER SUMMARY ===
{summary_json}
=====================

For EACH method identified, assess:
  1. Does it determine the DIRECTION of neural projections (source → target)?
  2. Was it applied to human brain tissue (in vivo or post-mortem)?
  3. What is the confidence that the method reveals directed connectivity?

Return a JSON object with EXACTLY this structure:
{{
  "pubmed_id": "{pubmed_id}",
  "methods_found": [
    {{
      "method_name": "<standardised name — e.g. 'DTI tractography', 'AAV anterograde tracing', 'SEEG-CCEP', 'Granger causality fMRI'>",
      "method_category": "<one of: anterograde_tracing | retrograde_tracing | viral_vector | dMRI_tractography | fMRI_connectivity | eeg_meg_electrophysiology | invasive_electrophysiology | tissue_clearing | sequencing_based | optogenetics | pharmacological | lesion_based | other>",
      "applied_to_human": <true | false>,
      "directionality_type": "<one of: anterograde_defined | retrograde_defined | functional_directed | structural_undirected | bidirectional_ambiguous | unclear>",
      "direction_confidence": "<one of: high | medium | low | none>",
      "how_direction_was_determined": "<one sentence describing how the method established or failed to establish direction>",
      "source_region": "<brain region or null>",
      "target_region": "<brain region or null>",
      "evidence_sentence": "<direct quote or close paraphrase from abstract confirming this method was used>"
    }}
  ],
  "no_methods_found": <true if the paper does not study neural projections at all>
}}
"""


# ==========================================================================
#  STAGE 3 — EVIDENCE-GROUNDED DIRECTIONALITY SCORING
# ==========================================================================
#
#  Input  : all Stage 2 method extraction records, aggregated per method
#  Output : a 0–1 directionality score for each unique method, grounded
#           in the actual paper evidence collected in Stages 1 and 2
# ==========================================================================

STAGE3_SYSTEM = """\
You are a senior neuroscience methods reviewer with expertise in neural
circuit tracing and connectivity mapping.

You have been given a body of evidence extracted from a large literature survey
(~1100 papers) about how a particular experimental method has been used to study
neural projections. Your task is to assign a DIRECTIONALITY SCORE to the method.

The directionality score (0.0 – 1.0) quantifies how well this method can
determine the DIRECTION of a neural projection (i.e., which region is the
source and which is the target), specifically in the HUMAN brain.

Scoring rubric (apply all criteria, integrate into one score):

  [CR1] Direct anatomical directionality (weight: HIGHEST)
        Do papers using this method unambiguously identify source and target?
        e.g., anterograde tracer injection = source confirmed;
              retrograde tracer = target confirmed;
              DTI tractography = neither confirmed (orientation only, not direction).

  [CR2] Human brain applicability (weight: HIGH)
        What fraction of papers used this method in human tissue
        (in vivo or post-mortem)?  Animal-only methods are penalised.

  [CR3] Causal / perturbational evidence (weight: MEDIUM-HIGH)
        Do papers use this method to establish causation
        (stimulate A → observe B), not just correlation?

  [CR4] Synaptic specificity (weight: MEDIUM)
        Does the method distinguish monosynaptic from polysynaptic projections?

  [CR5] Spatial resolution (weight: MEDIUM)
        Can the method resolve individual neurons or only broad regions?

  [CR6] Temporal resolution (weight: LOW-MEDIUM)
        For electrophysiology / imaging methods: is millisecond-scale
        temporal precedence available to infer direction?

  [CR7] Coverage consistency (weight: LOW)
        Are the study findings consistent across papers, or highly variable?

CRITICAL KNOWN CONSTRAINTS (penalise automatically if applicable):
  - DTI/dMRI tractography: physically CANNOT distinguish ascending from
    descending fibers — CR1 must be at most 0.20.
  - fMRI Granger causality: hemodynamic response confounds temporal ordering —
    CR3 penalty applies.
  - Methods applied ONLY in animals: CR2 = 0.10 or lower.

Output ONLY a valid JSON object — no preamble, no markdown fences.
"""

STAGE3_USER_TEMPLATE = """\
Score the following experimental method for its ability to observe DIRECTED
neural projections in the HUMAN brain.

=== METHOD ===
Name     : {method_name}
Category : {method_category}

=== EVIDENCE FROM {n_papers} PAPERS ===
Human-applicable papers : {n_human} / {n_papers}
High-confidence directional papers : {n_high_conf} / {n_papers}

Direction type breakdown:
{direction_breakdown}

Sample evidence records (up to 10 most informative):
{evidence_records}
==============================

Based on this literature evidence, assign a directionality score.
Your score must be grounded in the actual paper evidence above.
Do not rely solely on your prior knowledge — use the evidence distribution.

Return a JSON object with EXACTLY this structure:
{{
  "method_name": "{method_name}",
  "method_category": "{method_category}",
  "n_papers_evidence": {n_papers},
  "n_papers_human": {n_human},
  "directionality_score": <float 0.0 – 1.0>,
  "criterion_scores": {{
    "CR1_anatomical_directionality": <float 0-1>,
    "CR2_human_applicability": <float 0-1>,
    "CR3_causal_perturbational": <float 0-1>,
    "CR4_synaptic_specificity": <float 0-1>,
    "CR5_spatial_resolution": <float 0-1>,
    "CR6_temporal_resolution": <float 0-1>,
    "CR7_coverage_consistency": <float 0-1>
  }},
  "human_applicable": <true | false>,
  "animal_only": <true | false>,
  "score_rationale": "<3-5 sentence justification grounded in the paper evidence>",
  "score_rationale_ja": "<same in Japanese>",
  "key_limitations": ["<limitation 1>", "<limitation 2>"],
  "representative_papers": ["<pubmed_id — title (year)>"]
}}
"""

# ==========================================================================
#  STAGE 3b — FINAL COMPARATIVE SUMMARY
# ==========================================================================
#  After all methods are scored, produce a ranked comparison and
#  WholeBIF-RDB integration recommendations.
# ==========================================================================

STAGE3_SUMMARY_SYSTEM = STAGE3_SYSTEM  # reuse same expert role

STAGE3_SUMMARY_USER_TEMPLATE = """\
You have scored {n_methods} experimental methods for directed neural projection
observation in the human brain. The full scored results are below.

{scored_json}

Generate a final comparative report as JSON:
{{
  "ranked_human_applicable": [
    {{"rank": 1, "method_name": "...", "score": 0.0, "one_line_reason": "..."}}
  ],
  "ranked_overall": [
    {{"rank": 1, "method_name": "...", "score": 0.0, "one_line_reason": "..."}}
  ],
  "optimal_strategy": "<recommended multi-method combination for mapping directed human brain projections>",
  "optimal_strategy_ja": "<same in Japanese>",
  "wholebif_rdb_pder_weights": {{
    "<method_name>": <float weight to apply to PDER for papers using this method>
  }},
  "wholebif_rdb_notes": "<how to integrate these scores into manual_to_bdbra_converter.py and PDER computation>"
}}
"""
