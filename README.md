
    # BDBRA-build-v2 — Build & Data Ingestion Toolkit

    > End-to-end toolkit for building **BDBRA** (Brain Database for Brain Reference Architecture) and ingesting connectivity evidence into a relational database, with a minimal **Gradio** app for browsing.

    This README covers dependencies, local & Docker setup, database initialization, CSV/Sheets imports, typical workflows, and troubleshooting. All comments and docs are standardized to **English** for collaboration.

    ---

    ## Features

    - **PostgreSQL 16**-ready DDL and migration scripts
    - Ingestion pipelines: CSV & Google Sheets → DB (idempotent upsert)
    - Normalized tables aligned with WholeBIF/WholeBIF‑RDB conventions
    - Gradio-based lightweight UI for querying circuits, connections, references, evidence, and scores
    - Reproducible env (conda/Poetry) and **Docker Compose** support
    - Comment policy & i18n: English-only

    ---

    ## Repository Layout

    See `FILES.md` for the full tree. A condensed view:

    ```text
    BDBRA-build-v2_clean/
└── BDBRA-build-v2
    ├── dhba
    │   └── BrainRegions.csv
    ├── sample
    │   ├── 10519872_citations_refaware_basic.csv
    │   ├── PMC12376052.txt
    │   ├── reemergent_tremor_citation_sentiment_demo.csv
    │   └── sample_BDBRA.xlsx
    ├── src
    │   ├── hav_pubmed
    │   │   ├── harvest_pubmed_projections_pro_nofulltext_fast.py
    │   │   ├── harvest_pubmed_projections_pro_nofulltext_fast_split_2.py
    │   │   └── harvest_pubmed_projections_pro_v2.py
    │   ├── neural_projection_bundle
    │   │   ├── tools
    │   │   │   ├── html_text.py
    │   │   │   └── pdf_text.py
    │   │   ├── batch_llm_pubmed10_ncbi.py
    │   │   ├── batch_pubmed_until_target.py
    │   │   ├── batch_pubmed_until_target_history.py
    │   │   ├── batch_pubmed_until_target_sharded.py
    │   │   ├── doi_utils.py
    │   │   ├── llm_extract_single.py
    │   │   ├── method_lexicon.py
    │   │   ├── NeuralProjection_Colab.ipynb
    │   │   └── prompts_llm.py
    │   ├── relaiblity_score
    │   │   ├── citation_sentiment_prod_plus_transformers.ipynb
    │   │   ├── citation_sentiment_refaware_basic_v2.ipynb
    │   │   └── reemergent_tremor_citation_sentiment_demo.ipynb
    │   ├── vis_tool
    │   │   └── gradio_wholebif_query_app_flexpair_public_v2_fix2.py
    │   └── extract_bandle
    ├── LICENSE
    └── README.md
    ... (see FILES.md for the full tree)
    ```

    ---

    ## 1. Requirements

    ### Option A: Local (Python 3.11+)
    - Python 3.11 (3.10 works in most cases)
    - PostgreSQL 16 (or compatible managed instance)
    - (Recommended) `psql` client, `libpq` headers
    - Conda or Poetry

    ### Option B: Docker
    - Docker 24+
    - Docker Compose v2+

    ---

    ## 2. Quick Start (Docker)

    ```bash
    cp .env.example .env
    # Edit credentials:
    # POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
    # APP_HOST, APP_PORT
    # Optional: GOOGLE_SHEETS_* / OPENAI_*

    docker compose up -d --build

    # Run migrations and seed
    docker compose exec app python scripts/db_migrate.py
    docker compose exec app python scripts/seed_demo.py

    # Open UI
    # http://localhost:${APP_PORT:-7860}
    ```

    Stop stack:

    ```bash
    docker compose down -v
    ```

    ---

    ## 3. Quick Start (Local)

    ```bash
    # Create env
    conda create -n bdbrabuild python=3.11 -y
    conda activate bdbrabuild

    pip install -U pip wheel setuptools
    pip install -r requirements.txt  # or: poetry install

    cp .env.example .env
    # configure Postgres DSN

    # Initialize DB
    python scripts/db_migrate.py

    # Import CSV (example)
    python scripts/import_from_csv.py data/incoming/*.csv

    # Launch Gradio app
    python gradio_app.py --host 0.0.0.0 --port 7860
    ```

    ---

    ## 4. Environment Variables

    - `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
    - `APP_HOST` (default `0.0.0.0`), `APP_PORT` (default `7860`)
    - Optional import: `GOOGLE_SHEETS_CREDENTIALS_JSON`, `SHEETS_DOC_ID`
    - Optional scoring: `OPENAI_API_KEY`
    - `TZ` (default `Asia/Tokyo`), `LOG_LEVEL` (default `INFO`)

    ---

    ## 5. Database

    **Core tables** (typical):

    - `circuits`: `circuit_id (PK)`, `names`, `uniform`, `subcircuit[]`, `status`
    - `connections`: `(circuit_id, receiver_id)`, `connection_flag`, `status`
    - `evidence`: quotes, figure pointers, `reference_id`, `status`
    - `references_tbl`: `reference_id`, `title`, `doc_link (DOI URL)`, `bibtex_link`, `doi`, `journal_names`, `contributor`
    - `scores`: `pder`, `dsi`, `methodscore`, `citationscore` (attached per connection)
    - `changelog`: provenance of updates

    **Migrations**

    ```bash
    python scripts/db_migrate.py
    ```

    **Seed (optional)**

    ```bash
    python scripts/seed_demo.py
    ```

    ---

    ## 6. Data Import

    ### CSV

    ```bash
    python scripts/import_from_csv.py data/incoming/your.csv       --table connections       --if-exists upsert
    ```

    ### Google Sheets

    ```bash
    python scripts/import_from_sheets.py --sheet "Connections"
    ```

    ---

    ## 7. Gradio UI

    ```bash
    python gradio_app.py --host 0.0.0.0 --port 7860       --concurrency 4 --max-queue 64
    ```

    **Navigation**

    1. Search circuits by name/abbrev
    2. Click a *Receiver ID* to pivot
    3. Expand *Subcircuits* to view details (connections, evidence, references, scores)

    ---

    ## 8. Development

    - Code style: `ruff` + `black`
    - Types: `mypy`
    - Tests: `pytest`

    ```bash
    pip install -r requirements-dev.txt
    ruff check .
    black .
    mypy .
    pytest
    ```

    ---

    ## 9. Comment Policy & i18n

    All user-facing strings, docstrings, and comments are in **English**.  
    A detector report is available at `jp_comment_report.csv`. Remaining non-English fragments should be translated before merge.

    ---

    ## 10. Troubleshooting

    - `psycopg` connection errors → verify Postgres host/port/user/password
    - Gradio `concurrency_count` error → use `--concurrency` (Gradio 4+)
    - CSV width errors (e.g., `value too long for character varying(255)`) → widen columns or truncate in importer; see `migrations/*alter_columns*.sql`

    ---

    ## License

    MIT (unless otherwise stated in subdirectories)
