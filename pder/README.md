# Neural Projection Directionality Scoring Pipeline

3-stage LLM pipeline for scoring experimental methods on their ability
to observe **directed** neural projections in the human brain.

Part of the **WholeBIF-RDB** project (Nihon University).

---

## How the pipeline works

```
papers_input.csv          (~1100 papers: pubmed_id, title, abstract, fulltext)
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│  STAGE 1  stage1_summarize.py                           │
│                                                         │
│  Prompt: STAGE1_SYSTEM + STAGE1_USER_TEMPLATE           │
│  Per paper: summarise key finding, species, brain       │
│  regions, method approach                               │
│                                                         │
│  Output: stage1_summaries.jsonl  (1 JSON obj / paper)   │
└─────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│  STAGE 2  stage2_extract_methods.py                     │
│                                                         │
│  Prompt: STAGE2_SYSTEM + STAGE2_USER_TEMPLATE           │
│  Per paper: extract each method used, its category,     │
│  whether it determined direction and how, whether       │
│  applied to human brain                                 │
│                                                         │
│  Output: stage2_methods.jsonl        (raw per-paper)    │
│          stage2_method_index.json    (aggregated:       │
│                             method → list of evidence)  │
└─────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│  STAGE 3  stage3_score_methods.py                       │
│                                                         │
│  Prompt: STAGE3_SYSTEM + STAGE3_USER_TEMPLATE           │
│  Per method: send aggregated evidence (paper count,     │
│  human fraction, direction type breakdown, top-10       │
│  evidence records) → LLM assigns 0–1 score grounded    │
│  in the actual paper evidence, not just prior knowledge │
│                                                         │
│  Output: stage3_scores.json  (scores + PDER weights)   │
└─────────────────────────────────────────────────────────┘
```

---

## Files

```
pipeline.py                     ← Orchestrator (run this)
prompts.py                      ← All prompts (fully transparent)
stages/
  stage1_summarize.py           ← Stage 1 script
  stage2_extract_methods.py     ← Stage 2 script
  stage3_score_methods.py       ← Stage 3 script
data/
  papers_input.csv              ← YOUR INPUT (you provide this)
  papers_input_example.csv      ← Format example (5 papers)
  stage1_summaries.jsonl        ← Stage 1 output
  stage2_methods.jsonl          ← Stage 2 output (raw)
  stage2_method_index.json      ← Stage 2 output (indexed)
  stage3_scores.json            ← FINAL OUTPUT
```

---

## Quick start

### 1. Install

```bash
pip install anthropic openai
```

### 2. Prepare input

Your `data/papers_input.csv` must have these columns:

| Column      | Required | Description                       |
|-------------|----------|-----------------------------------|
| `pubmed_id` | Yes      | PubMed ID or any unique string    |
| `title`     | Yes      | Paper title                       |
| `abstract`  | Yes      | Abstract text                     |
| `fulltext`  | No       | Full text (first 3000 chars used) |

### 3. Set API key

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
# or
export OPENAI_API_KEY="sk-..."
```

### 4. Run

```bash
# Full pipeline with Claude (default)
python pipeline.py --api claude

# Resume after interruption
python pipeline.py --api claude --resume

# Skip Stage 1 (already done), run stages 2–3
python pipeline.py --api claude --stages 2 3

# Test with first 20 papers
python pipeline.py --api claude --limit 20 --verbose

# Use GPT-4.1 instead
python pipeline.py --api openai --model gpt-4.1
```

---

## Prompts explained (prompts.py)

### Stage 1 — STAGE1_SYSTEM + STAGE1_USER_TEMPLATE

Instructs the LLM to produce a structured JSON summary for each paper,
capturing: species, brain regions studied, key finding, and whether
the paper involves neural projection tracing at all
(`uses_neural_projection_tracing: true/false`).

This flag is used in Stage 2 to skip papers that aren't relevant,
saving API calls.

### Stage 2 — STAGE2_SYSTEM + STAGE2_USER_TEMPLATE

For each paper that involves neural projections, the LLM identifies
every experimental method used and classifies:
- `method_category` (anterograde_tracing, dMRI_tractography, etc.)
- `directionality_type` (anterograde_defined / retrograde_defined /
  functional_directed / structural_undirected / unclear)
- `direction_confidence` (high / medium / low / none)
- `how_direction_was_determined` (one sentence)
- `applied_to_human` (true/false)
- `evidence_sentence` (quote from abstract)

The Stage 2 index aggregates all these records per canonical method name.

### Stage 3 — STAGE3_SYSTEM + STAGE3_USER_TEMPLATE

The scoring prompt is built with **computed statistics from the actual
paper evidence**:

```
Human-applicable papers      : X / N
High-confidence directional  : Y / N
Direction type breakdown:
  anterograde_defined        : ...
  structural_undirected      : ...
  ...
Sample evidence records (top 10 most informative):
  [...]
```

The LLM is explicitly told: *"Your score must be grounded in the actual
paper evidence above. Do not rely solely on your prior knowledge."*

The 7 scoring criteria (CR1–CR7) are defined in `STAGE3_SYSTEM`:

| Criterion | Weight    |
|-----------|-----------|
| CR1 Anatomical directionality | HIGHEST |
| CR2 Human applicability       | HIGH    |
| CR3 Causal/perturbational     | MED-HIGH|
| CR4 Synaptic specificity      | MED     |
| CR5 Spatial resolution        | MED     |
| CR6 Temporal resolution       | LOW-MED |
| CR7 Coverage consistency      | LOW     |

---

## Output format (stage3_scores.json)

```json
{
  "pipeline_stage": 3,
  "scored_methods": [
    {
      "method_name": "SEEG + CCEP",
      "directionality_score": 0.87,
      "criterion_scores": {
        "CR1_anatomical_directionality": 0.92,
        "CR2_human_applicability": 0.95,
        ...
      },
      "n_papers_evidence": 42,
      "human_applicable": true,
      "score_rationale": "...",
      "score_rationale_ja": "...",
      "key_limitations": ["..."],
      "representative_papers": ["pubmed_id — title (year)"],
      "_n_papers": 42,
      "_n_human": 38
    }
  ],
  "summary": {
    "ranked_human_applicable": [...],
    "optimal_strategy": "...",
    "optimal_strategy_ja": "...",
    "wholebif_rdb_pder_weights": {
      "SEEG + CCEP": 0.87,
      "DTI tractography": 0.32,
      ...
    }
  }
}
```

---

## WholeBIF-RDB integration

Use `summary.wholebif_rdb_pder_weights` from `stage3_scores.json` as
multipliers in the PDER computation inside
`import_bdbra_into_wholebif_v4_enhanced_patched.py`:

```python
import json

with open("data/stage3_scores.json") as f:
    pipeline_output = json.load(f)

PDER_WEIGHTS = pipeline_output["summary"]["wholebif_rdb_pder_weights"]

def adjusted_pder(base_pder: float, source_method: str) -> float:
    weight = PDER_WEIGHTS.get(source_method, 0.5)  # default 0.5 if unknown
    return base_pder * weight
```

Store `source_method` (the canonical method name from Stage 2) in the
BDBRA record's `source_method` field during manual curation in
`manual_to_bdbra_converter.py`.
