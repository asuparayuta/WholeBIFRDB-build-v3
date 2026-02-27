# WholeBIF-RDB Pipeline

Data ingestion pipeline for WholeBIF-RDB (Whole Brain Interconnection Fluency - Research Database). Takes new neural connectivity records from Google Spreadsheet exports, computes credibility scores (PDER, CSI, CR), and outputs BDBRA CSV ready for database import.

## What This Pipeline Does

WholeBIF-RDB is a database of neural projections in the brain. Each record carries a **Credibility Rating (CR)** — a composite reliability score computed as the product of six component scores:

```
CR = Source Region Score x Receiver Region Score x CSI x Literature Type Score x Taxon Score x PDER
```

This pipeline handles the red-boxed portion of the architecture diagram below:

```
Google Spreadsheet (wbConnections / wbReferences)
        |
        v
+------------------------------------+
|  manual_to_bdbra_converter.py      |  <-- this repository
|    +-- schema.py                   |
|    +-- credibility_calculator.py   |
|    +-- pipeline.py                 |
+------------------------------------+
        |
        v
   BDBRA CSV  ->  import_bdbra_into_wholebif.py  ->  PostgreSQL
```

## Directory Structure

```
.
+-- src/                         Source code
|   +-- schema.py                  Data types and validation (344 lines)
|   +-- credibility_calculator.py  PDER, CSI, and CR computation (307 lines)
|   +-- manual_to_bdbra_converter.py  CSV converter (398 lines)
|   +-- pipeline.py                Orchestrator (226 lines)
|
+-- tests/                       Tests (99 tests, all passing)
|   +-- conftest.py                Shared fixtures
|   +-- test_credibility.py        Credibility scoring tests (45 tests)
|   +-- test_converter.py          Converter tests (31 tests)
|   +-- test_pipeline.py           Integration tests (23 tests)
|
+-- tools/                       Standalone tools
|   +-- score_pder_with_claude_api.py   Batch PDER scoring (Claude API)
|   +-- score_citation_sentiment.py     Batch CSI scoring (Semantic Scholar + Claude API)
|
+-- docs/                        Documentation
|   +-- architecture.md            Pipeline architecture diagram
|   +-- test_design.md             Test design document (design rationale for all 99 tests)
|   +-- test_results.md            Test execution report
|
+-- data/                        Data directory (CSV files gitignored; place locally)
+-- pyproject.toml               Project configuration
+-- README.md                    This file
```

## Setup

```bash
git clone https://github.com/<your-org>/wholebif-rdb-pipeline.git
cd wholebif-rdb-pipeline
pip install pytest pytest-cov requests
```

## Usage

### Pipeline Execution (Heuristic Mode)

Uses rule-based scoring with no external API calls. Suitable for testing and dry runs.

```bash
python src/pipeline.py \
  -c data/new_connections.csv \
  -r data/new_references.csv \
  -o ./output \
  --contributor "YourName" \
  --project-id "PROJECT01" \
  --dry-run
```

### Pipeline Execution (High-Accuracy Mode)

Uses Claude API for PDER and Semantic Scholar API for CSI. For production use.

```bash
export ANTHROPIC_API_KEY="your-key"
python src/pipeline.py \
  -c data/new_connections.csv \
  -r data/new_references.csv \
  -o ./output \
  --contributor "YourName" \
  --project-id "PROJECT01"
```

### Standalone Tools

For batch scoring an existing wbConnections CSV:

```bash
# Batch PDER scoring (Claude API)
export ANTHROPIC_API_KEY="your-key"
python tools/score_pder_with_claude_api.py \
  -i data/WholeBIF_RDBv2_wbConnections.csv \
  -o data/WholeBIF_RDBv2_scored.csv

# Batch CSI scoring (Semantic Scholar + Claude API)
python tools/score_citation_sentiment.py \
  -i data/WholeBIF_RDBv2_wbConnections.csv \
  -r data/WholeBIF_RDBv2_wbReferences.csv \
  -o data/WholeBIF_RDBv2_scored.csv
```

## Tests

```bash
# Run all 99 tests
python -m pytest tests/ -v

# With coverage report
python -m pytest tests/ --cov=src --cov-report=term-missing

# Run specific tests
python -m pytest tests/test_credibility.py::TestCRCalculation -v
python -m pytest tests/ -k "pder" -v
```

### Test Results (as of 2026-02-27)

```
99 passed in 0.41s

src/schema.py                    99%
src/manual_to_bdbra_converter.py 73%
src/pipeline.py                  69%
src/credibility_calculator.py    53%
TOTAL                            74%
```

See [docs/test_design.md](docs/test_design.md) for design rationale and [docs/test_results.md](docs/test_results.md) for full execution logs.

## CR Calculation Verification

Pipeline calculations have been verified against real data from WholeBIF_RDBv2:

| Row | Scores (6 components) | Expected CR | Computed |
|-----|----------------------|-------------|----------|
| Row 176 | (1, 1, 0.95, 1, 0.5, 0.4) | 0.190 | Match |
| Row 319 | (1, 1, 0.95, 1, 0.6, 0.8) | 0.456 | Match |
| Row 181 | (1, 1, 0.95, 0.5, 0.5, 0.3) | 0.0712 | Match |

## PDER Score Reference

PDER scores by measurement method category. Methods with stronger directional evidence score higher.

```
Method Category             Score Range   Rows in Existing Data
-------------------------------------------------------------
Various tracing             0.85-0.95       200
Tracer study                0.80-0.95     1,094
Electrophys / Opto/Chemo    0.55-0.75     2,266
DTI / tractography          0.35-0.55       815
fMRI / rs-fMRI              0.30-0.50     1,500+
Review / Unspecified        0.20-0.40    18,159
Textbook                    0.15-0.35        54
```

## License

MIT License

## Related Resources

- [WholeBIF-RDB Project](https://wholebif.org) (Nihon University)
- [BDBRA Format Specification](https://wholebif.org/bdbra)
