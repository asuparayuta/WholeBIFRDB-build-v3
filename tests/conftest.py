"""
conftest.py - Shared test fixtures for WholeBIF pipeline tests.
"""

import csv
import os
import pytest
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from schema import ConnectionRecord, ReferenceRecord
from credibility_calculator import CredibilityCalculator
from manual_to_bdbra_converter import ManualToBdbraConverter


# ============================================================
# Sample Reference Data
# ============================================================

SAMPLE_REFERENCES = [
    {
        "reference_id": "Smith, 2020",
        "doc": "DOC",
        "bib": "BIB",
        "doi": "10.1234/test.2020.001",
        "bibtex": '@article{Smith_2020, doi={10.1234/test.2020.001}, year=2020}',
        "literature_type": "",
        "article_type": "Article",
        "authors": "John Smith, Jane Doe",
        "title": "Anterograde tracing of hippocampal CA1 projections",
        "journal": "Journal of Neuroscience",
        "contributor": "TestContributor",
    },
    {
        "reference_id": "Tanaka, 2019",
        "doc": "DOC",
        "bib": "BIB",
        "doi": "10.1234/test.2019.002",
        "bibtex": '@article{Tanaka_2019, doi={10.1234/test.2019.002}, year=2019}',
        "literature_type": "",
        "article_type": "Review",
        "authors": "Yuki Tanaka",
        "title": "Review of cerebellar connectivity",
        "journal": "Nature Reviews Neuroscience",
        "contributor": "TestContributor",
    },
    {
        "reference_id": "Lee, 2023",
        "doc": "DOC",
        "bib": "BIB",
        "doi": "10.1234/test.2023.003",
        "bibtex": "",
        "literature_type": "",
        "article_type": "Article",
        "authors": "Soo-Jin Lee",
        "title": "Optogenetic mapping of basal ganglia circuits",
        "journal": "Neuron",
        "contributor": "TestContributor",
    },
]

SAMPLE_CONNECTIONS = [
    {
        "sender_cid": "CA1",
        "receiver_cid": "Sub",
        "reference_id": "Smith, 2020",
        "taxon": "Rat",
        "measurement_method": "Tracer study",
        "literature_type": "Experimental results",
        "source_region_score": 1.0,
        "receiver_region_score": 1.0,
        "taxon_score": 0.6,
    },
    {
        "sender_cid": "CB",
        "receiver_cid": "VN",
        "reference_id": "Tanaka, 2019",
        "taxon": "Various",
        "measurement_method": "Review",
        "literature_type": "Review",
        "source_region_score": 1.0,
        "receiver_region_score": 1.0,
        "taxon_score": 0.5,
    },
    {
        "sender_cid": "STR",
        "receiver_cid": "GPe",
        "reference_id": "Lee, 2023",
        "taxon": "Mouse",
        "measurement_method": "optogenetics",
        "literature_type": "Experimental results",
        "source_region_score": 1.0,
        "receiver_region_score": 1.0,
        "taxon_score": 0.6,
    },
]


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a temporary directory."""
    return tmp_path


@pytest.fixture
def sample_references_csv(tmp_path):
    """Create a sample wbReferences CSV file."""
    csv_path = tmp_path / "test_references.csv"
    headers = [
        "#N/A", "DOC", "BIB", "DOI", "BibTex ", "Litterature type",
        "#N/A", "#N/A", "#N/A", "-", "Alternative URL",
        "Contributor", "Project ID",
    ]
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for ref in SAMPLE_REFERENCES:
            writer.writerow([
                ref["reference_id"], ref["doc"], ref["bib"], ref["doi"],
                ref["bibtex"], ref["literature_type"], ref["article_type"],
                ref["authors"], ref["title"], ref["journal"], "",
                ref["contributor"], "",
            ])
    return str(csv_path)


@pytest.fixture
def sample_connections_csv(tmp_path):
    """Create a sample wbConnections CSV file."""
    csv_path = tmp_path / "test_connections.csv"

    # Full 42-column header
    from schema import WB_CONNECTIONS_COLUMNS
    headers = WB_CONNECTIONS_COLUMNS

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for conn in SAMPLE_CONNECTIONS:
            row = [""] * len(headers)
            row[0] = conn["sender_cid"]
            row[3] = conn["receiver_cid"]
            row[8] = conn["reference_id"]
            row[9] = conn["taxon"]
            row[10] = conn["measurement_method"]
            row[16] = conn["literature_type"]
            row[20] = str(conn["source_region_score"])
            row[21] = str(conn["receiver_region_score"])
            row[24] = str(conn["taxon_score"])
            writer.writerow(row)
    return str(csv_path)


@pytest.fixture
def credibility_calc():
    """Provide a CredibilityCalculator in heuristic mode."""
    return CredibilityCalculator(use_api=False)


@pytest.fixture
def converter(credibility_calc):
    """Provide a ManualToBdbraConverter with test defaults."""
    return ManualToBdbraConverter(
        credibility_calc=credibility_calc,
        contributor="TestContributor",
        project_id="TEST01",
    )


# ============================================================
# Edge case fixtures
# ============================================================

@pytest.fixture
def empty_csv(tmp_path):
    """Create an empty CSV with only headers."""
    csv_path = tmp_path / "empty.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        f.write("col1,col2,col3\n")
    return str(csv_path)


@pytest.fixture
def malformed_connections_csv(tmp_path):
    """Create a CSV with validation errors."""
    csv_path = tmp_path / "malformed_connections.csv"
    from schema import WB_CONNECTIONS_COLUMNS
    headers = WB_CONNECTIONS_COLUMNS

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        # Row with missing sender_cid (required)
        row1 = [""] * len(headers)
        row1[3] = "Sub"
        row1[8] = "Smith, 2020"
        writer.writerow(row1)
        # Row with missing receiver_cid (required)
        row2 = [""] * len(headers)
        row2[0] = "CA1"
        row2[8] = "Smith, 2020"
        writer.writerow(row2)
        # Valid row
        row3 = [""] * len(headers)
        row3[0] = "CA1"
        row3[3] = "Sub"
        row3[8] = "Smith, 2020"
        row3[10] = "Tracer study"
        row3[16] = "Experimental results"
        row3[20] = "1.0"
        row3[21] = "1.0"
        row3[24] = "0.6"
        writer.writerow(row3)
    return str(csv_path)


@pytest.fixture
def references_with_missing_doi_csv(tmp_path):
    """Create references CSV where some entries lack DOI."""
    csv_path = tmp_path / "refs_no_doi.csv"
    headers = [
        "#N/A", "DOC", "BIB", "DOI", "BibTex ", "Litterature type",
        "#N/A", "#N/A", "#N/A", "-", "Alternative URL",
        "Contributor", "Project ID",
    ]
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerow([
            "NoDOI, 2020", "DOC", "BIB", "", "", "",
            "Article", "Author A", "Title", "Journal", "",
            "TestContributor", "",
        ])
    return str(csv_path)
