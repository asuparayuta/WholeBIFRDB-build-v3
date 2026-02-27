"""
WholeBIF-RDB Pipeline: Data Schema Definitions
================================================
Defines column schemas for wbConnections, wbReferences, and BDBRA CSV formats.
"""

from dataclasses import dataclass, field
from typing import Optional


# ============================================================
# wbConnections schema (42 columns)
# ============================================================

WB_CONNECTIONS_COLUMNS = [
    "Sender Circuit ID (sCID)",       # 0
    "sCID relation",                   # 1
    "Notation of sCID in Literature",  # 2
    "Receiver Circuit ID (rCID)",      # 3
    "rCID relation",                   # 4
    "Notation of rCID in Literature",  # 5
    "Size",                            # 6
    "Comments",                        # 7
    "Reference ID",                    # 8
    "Taxon",                           # 9
    "Measurement method",              # 10
    "Pointers on literature",          # 11
    "Pointers on figure",              # 12
    "In-depth literature",             # 13
    "Doc. Link",                       # 14
    "Journal names\t",                 # 15 (note: has trailing tab in original)
    "Litterature type",                # 16
    "Display string per join",         # 17
    "Combined string for search",      # 18
    "[Reference ID]",                  # 19
    "Souce region score",              # 20
    "Receiver region score",           # 21
    "Citation sentiment index",        # 22
    "Literature type score",           # 23
    "Taxon score",                     # 24
    "Method score (PDER)",             # 25
    "Credibility rating (CR)",         # 26
    "Summarized CR",                   # 27
    "Reviewed CR",                     # 28
    "Summarized Reviewed CR",          # 29
    "Contributor",                     # 30
    "Project ID",                      # 31
    "Contributor Response to Reviewers",  # 32
    "Status",                          # 33
    "Review results",                  # 34
    "Auto Error Codes",                # 35
    "Error Code-1",                    # 36
    "Error Code-2",                    # 37
    "Other Error Codes",               # 38
    "Review comments",                 # 39
    "Reviewer",                        # 40
    "Reviewed date",                   # 41
]

# wbReferences schema (23 columns)
WB_REFERENCES_COLUMNS = [
    "#N/A",              # 0  = Reference ID (e.g., "Amaral, 1991")
    "DOC",               # 1
    "BIB",               # 2
    "DOI",               # 3
    "BibTex ",           # 4
    "Litterature type",  # 5
    "#N/A",              # 6  = Article type
    "#N/A",              # 7  = Authors
    "#N/A",              # 8  = Title
    "-",                 # 9  = Journal
    "Alternative URL",   # 10
    "Contributor",       # 11
    "Project ID",        # 12
    "WBIF pull request", # 13
    "WBIF copied",       # 14
    "Review results",    # 15
    "Auto Error Codes",  # 16
    "Error Code-1",      # 17
    "Error Code-2",      # 18
    "Other Error Codes", # 19
    "Review comments",   # 20
    "Reviewer",          # 21
    "Reviewed date",     # 22
]


# ============================================================
# Data classes for typed records
# ============================================================

@dataclass
class ConnectionRecord:
    """A single wbConnections row."""
    sender_cid: str
    scid_relation: str = ""
    notation_scid: str = ""
    receiver_cid: str = ""
    rcid_relation: str = ""
    notation_rcid: str = ""
    size: str = ""
    comments: str = ""
    reference_id: str = ""
    taxon: str = ""
    measurement_method: str = ""
    pointers_on_literature: str = ""
    pointers_on_figure: str = ""
    in_depth_literature: str = ""
    doc_link: str = ""
    journal_name: str = ""
    literature_type: str = ""
    display_string: str = ""
    combined_search: str = ""
    reference_id_bracket: str = ""
    source_region_score: float = 0.0
    receiver_region_score: float = 0.0
    citation_sentiment_index: float = 0.0
    literature_type_score: float = 0.0
    taxon_score: float = 0.0
    method_score_pder: float = 0.0
    credibility_rating: float = 0.0
    summarized_cr: float = 0.0
    reviewed_cr: float = 0.0
    summarized_reviewed_cr: float = 0.0
    contributor: str = ""
    project_id: str = ""
    contributor_response: str = ""
    status: str = ""
    review_results: str = ""
    auto_error_codes: str = ""
    error_code_1: str = ""
    error_code_2: str = ""
    other_error_codes: str = ""
    review_comments: str = ""
    reviewer: str = ""
    reviewed_date: str = ""

    def to_row(self) -> list:
        """Convert to CSV row (list of strings)."""
        return [
            self.sender_cid,
            self.scid_relation,
            self.notation_scid,
            self.receiver_cid,
            self.rcid_relation,
            self.notation_rcid,
            self.size,
            self.comments,
            self.reference_id,
            self.taxon,
            self.measurement_method,
            self.pointers_on_literature,
            self.pointers_on_figure,
            self.in_depth_literature,
            self.doc_link,
            self.journal_name,
            self.literature_type,
            self.display_string,
            self.combined_search,
            self.reference_id_bracket,
            str(self.source_region_score),
            str(self.receiver_region_score),
            str(self.citation_sentiment_index),
            str(self.literature_type_score),
            str(self.taxon_score),
            str(self.method_score_pder),
            f"{self.credibility_rating:.3f}",
            f"{self.summarized_cr:.3f}",
            f"{self.reviewed_cr:.3f}",
            f"{self.summarized_reviewed_cr:.3f}",
            self.contributor,
            self.project_id,
            self.contributor_response,
            self.status,
            self.review_results,
            self.auto_error_codes,
            self.error_code_1,
            self.error_code_2,
            self.other_error_codes,
            self.review_comments,
            self.reviewer,
            self.reviewed_date,
        ]

    @classmethod
    def from_row(cls, row: list) -> "ConnectionRecord":
        """Create from CSV row."""
        def safe_float(val, default=0.0):
            try:
                return float(val.strip()) if val.strip() else default
            except (ValueError, AttributeError):
                return default

        def safe_str(idx):
            return row[idx].strip() if idx < len(row) and row[idx] else ""

        return cls(
            sender_cid=safe_str(0),
            scid_relation=safe_str(1),
            notation_scid=safe_str(2),
            receiver_cid=safe_str(3),
            rcid_relation=safe_str(4),
            notation_rcid=safe_str(5),
            size=safe_str(6),
            comments=safe_str(7),
            reference_id=safe_str(8),
            taxon=safe_str(9),
            measurement_method=safe_str(10),
            pointers_on_literature=safe_str(11),
            pointers_on_figure=safe_str(12),
            in_depth_literature=safe_str(13),
            doc_link=safe_str(14),
            journal_name=safe_str(15),
            literature_type=safe_str(16),
            display_string=safe_str(17),
            combined_search=safe_str(18),
            reference_id_bracket=safe_str(19),
            source_region_score=safe_float(row[20] if 20 < len(row) else ""),
            receiver_region_score=safe_float(row[21] if 21 < len(row) else ""),
            citation_sentiment_index=safe_float(row[22] if 22 < len(row) else ""),
            literature_type_score=safe_float(row[23] if 23 < len(row) else ""),
            taxon_score=safe_float(row[24] if 24 < len(row) else ""),
            method_score_pder=safe_float(row[25] if 25 < len(row) else ""),
            credibility_rating=safe_float(row[26] if 26 < len(row) else ""),
            summarized_cr=safe_float(row[27] if 27 < len(row) else ""),
            reviewed_cr=safe_float(row[28] if 28 < len(row) else ""),
            summarized_reviewed_cr=safe_float(row[29] if 29 < len(row) else ""),
            contributor=safe_str(30),
            project_id=safe_str(31),
            contributor_response=safe_str(32),
            status=safe_str(33),
            review_results=safe_str(34),
            auto_error_codes=safe_str(35),
            error_code_1=safe_str(36),
            error_code_2=safe_str(37),
            other_error_codes=safe_str(38),
            review_comments=safe_str(39),
            reviewer=safe_str(40),
            reviewed_date=safe_str(41),
        )


@dataclass
class ReferenceRecord:
    """A single wbReferences row."""
    reference_id: str = ""
    doc: str = ""
    bib: str = ""
    doi: str = ""
    bibtex: str = ""
    literature_type: str = ""
    article_type: str = ""
    authors: str = ""
    title: str = ""
    journal: str = ""
    alternative_url: str = ""
    contributor: str = ""
    project_id: str = ""

    @classmethod
    def from_row(cls, row: list) -> "ReferenceRecord":
        def safe_str(idx):
            return row[idx].strip() if idx < len(row) and row[idx] else ""
        return cls(
            reference_id=safe_str(0),
            doc=safe_str(1),
            bib=safe_str(2),
            doi=safe_str(3),
            bibtex=safe_str(4),
            literature_type=safe_str(5),
            article_type=safe_str(6),
            authors=safe_str(7),
            title=safe_str(8),
            journal=safe_str(9),
            alternative_url=safe_str(10),
            contributor=safe_str(11),
            project_id=safe_str(12),
        )


# ============================================================
# Validation rules
# ============================================================

class ValidationError:
    """A single validation error."""
    def __init__(self, field: str, message: str, severity: str = "error"):
        self.field = field
        self.message = message
        self.severity = severity  # "error" or "warning"

    def __repr__(self):
        return f"[{self.severity.upper()}] {self.field}: {self.message}"


def validate_connection(rec: ConnectionRecord) -> list[ValidationError]:
    """Validate a ConnectionRecord. Returns list of errors/warnings."""
    errors = []

    # Required fields
    if not rec.sender_cid:
        errors.append(ValidationError("sender_cid", "Sender CID is required"))
    if not rec.receiver_cid:
        errors.append(ValidationError("receiver_cid", "Receiver CID is required"))
    if not rec.reference_id:
        errors.append(ValidationError("reference_id", "Reference ID is required"))

    # Reference ID format: "Author, YYYY"
    if rec.reference_id:
        import re
        if not re.match(r'^[A-Za-zÀ-ÿ\'\-]+,\s*\d{4}$', rec.reference_id):
            if rec.reference_id not in ("author, year", "#N/A"):
                errors.append(ValidationError(
                    "reference_id",
                    f"Reference ID '{rec.reference_id}' should be 'Author, YYYY' format",
                    severity="warning"
                ))

    # Score range validations
    score_fields = [
        ("source_region_score", rec.source_region_score),
        ("receiver_region_score", rec.receiver_region_score),
        ("citation_sentiment_index", rec.citation_sentiment_index),
        ("literature_type_score", rec.literature_type_score),
        ("taxon_score", rec.taxon_score),
        ("method_score_pder", rec.method_score_pder),
    ]
    for name, val in score_fields:
        if not (0.0 <= val <= 1.0):
            errors.append(ValidationError(name, f"Score {val} out of range [0.0, 1.0]"))

    return errors


def validate_reference(rec: ReferenceRecord) -> list[ValidationError]:
    """Validate a ReferenceRecord."""
    errors = []

    if not rec.reference_id:
        errors.append(ValidationError("reference_id", "Reference ID is required"))
    if not rec.doi and not rec.alternative_url:
        errors.append(ValidationError("doi", "Either DOI or alternative URL should be provided", "warning"))

    return errors
