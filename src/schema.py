"""
WholeBIF-RDB Pipeline: Data Schema Definitions
================================================

This module defines the canonical data schemas for the WholeBIF-RDB data
ingestion pipeline. It serves as the single source of truth for:

  - wbConnections CSV format (42 columns): Neural connectivity records
  - wbReferences CSV format (23 columns): Literature reference records
  - Typed dataclasses for safe, structured access to record fields
  - Validation rules that enforce data integrity before database import

The column definitions here must match the Google Spreadsheet headers exactly,
including known quirks such as trailing tabs and "#N/A" placeholders that
appear in the production spreadsheet. Changing column order or names here
will break CSV round-tripping, so proceed with caution.

Note on column naming:
    The original spreadsheet contains some inconsistencies (e.g., "Souce"
    instead of "Source", "Litterature" instead of "Literature"). These are
    preserved intentionally to maintain compatibility with existing data.
"""

from dataclasses import dataclass, field
from typing import Optional


# ============================================================================
# wbConnections Column Schema (42 columns)
# ============================================================================
#
# Each row in wbConnections represents a single neural projection
# (one brain region projecting to another), sourced from a published paper.
#
# Columns 0-19: Descriptive fields (regions, methods, references)
# Columns 20-26: Credibility scores (6 component scores + final CR)
# Columns 27-29: Aggregated/reviewed CR variants
# Columns 30-41: Administrative fields (contributor, review status, etc.)

WB_CONNECTIONS_COLUMNS = [
    "Sender Circuit ID (sCID)",       # 0  - Brain region where the projection originates (e.g., "CA1")
    "sCID relation",                   # 1  - Hierarchical relation of the sender region
    "Notation of sCID in Literature",  # 2  - How the sender region was named in the original paper
    "Receiver Circuit ID (rCID)",      # 3  - Brain region where the projection terminates (e.g., "Sub")
    "rCID relation",                   # 4  - Hierarchical relation of the receiver region
    "Notation of rCID in Literature",  # 5  - How the receiver region was named in the original paper
    "Size",                            # 6  - Projection strength/density descriptor (e.g., "moderate")
    "Comments",                        # 7  - Free-text notes about this connection
    "Reference ID",                    # 8  - Literature citation in "Author, YYYY" format
    "Taxon",                           # 9  - Experimental species (e.g., "Rat", "Mouse", "Macaque")
    "Measurement method",              # 10 - Technique used (e.g., "Tracer study", "fMRI", "Review")
    "Pointers on literature",          # 11 - Page/section references in the source paper
    "Pointers on figure",              # 12 - Figure references in the source paper
    "In-depth literature",             # 13 - Additional supporting references
    "Doc. Link",                       # 14 - URL or document link to the source paper
    "Journal names\t",                 # 15 - Journal name (NOTE: trailing tab exists in production data)
    "Litterature type",                # 16 - Category: "Experimental results", "Review", "Textbook", etc.
    "Display string per join",         # 17 - Pre-formatted string for UI display (auto-generated)
    "Combined string for search",      # 18 - Concatenation of sender+receiver CIDs for search indexing
    "[Reference ID]",                  # 19 - Reference ID wrapped in brackets (auto-generated)
    "Souce region score",              # 20 - Score for sender region identification accuracy [0-1]
    "Receiver region score",           # 21 - Score for receiver region identification accuracy [0-1]
    "Citation sentiment index",        # 22 - CSI: how positively/negatively the paper is cited [0-1]
    "Literature type score",           # 23 - Score based on publication type [0-1]
    "Taxon score",                     # 24 - Score for species relevance/closeness [0-1]
    "Method score (PDER)",             # 25 - Projection Direction Evaluation Rating [0-1]
    "Credibility rating (CR)",         # 26 - Final CR = product of all 6 scores above
    "Summarized CR",                   # 27 - CR aggregated across multiple records for the same projection
    "Reviewed CR",                     # 28 - CR after expert review
    "Summarized Reviewed CR",          # 29 - Aggregated reviewed CR
    "Contributor",                     # 30 - Person who entered this record
    "Project ID",                      # 31 - Project identifier (e.g., "HP01", "CB01")
    "Contributor Response to Reviewers",  # 32 - Response to review feedback
    "Status",                          # 33 - Record status in the review workflow
    "Review results",                  # 34 - Reviewer's assessment
    "Auto Error Codes",                # 35 - Machine-detected errors
    "Error Code-1",                    # 36 - First error code
    "Error Code-2",                    # 37 - Second error code
    "Other Error Codes",               # 38 - Additional error codes
    "Review comments",                 # 39 - Reviewer's free-text comments
    "Reviewer",                        # 40 - Name of the reviewer
    "Reviewed date",                   # 41 - Date of last review
]

# ============================================================================
# wbReferences Column Schema (23 columns)
# ============================================================================
#
# Each row represents a single published paper used as a data source.
# The first column header in the production spreadsheet is literally "#N/A"
# (a Google Sheets artifact), but it contains the Reference ID.

WB_REFERENCES_COLUMNS = [
    "#N/A",              # 0  - Reference ID (e.g., "Amaral, 1991") — header is a Sheets artifact
    "DOC",               # 1  - Document link/URL
    "BIB",               # 2  - Bibliography entry
    "DOI",               # 3  - Digital Object Identifier (e.g., "10.1002/hipo.450010410")
    "BibTex ",           # 4  - BibTeX entry (NOTE: trailing space in production header)
    "Litterature type",  # 5  - Literature type (same categories as wbConnections col 16)
    "#N/A",              # 6  - Article type (header is a Sheets artifact)
    "#N/A",              # 7  - Authors (header is a Sheets artifact)
    "#N/A",              # 8  - Title (header is a Sheets artifact)
    "-",                 # 9  - Journal name (header is a dash in production data)
    "Alternative URL",   # 10 - Fallback URL when DOI is unavailable
    "Contributor",       # 11 - Person who registered this reference
    "Project ID",        # 12 - Associated project identifier
    "WBIF pull request", # 13 - Pull request ID for WBIF integration
    "WBIF copied",       # 14 - Whether this reference has been copied to WBIF
    "Review results",    # 15 - Reviewer's assessment of this reference
    "Auto Error Codes",  # 16 - Machine-detected errors
    "Error Code-1",      # 17 - First error code
    "Error Code-2",      # 18 - Second error code
    "Other Error Codes", # 19 - Additional error codes
    "Review comments",   # 20 - Reviewer's comments
    "Reviewer",          # 21 - Name of the reviewer
    "Reviewed date",     # 22 - Date of last review
]


# ============================================================================
# ConnectionRecord Dataclass
# ============================================================================

@dataclass
class ConnectionRecord:
    """
    A typed representation of a single row in wbConnections (42 columns).

    This dataclass provides named, typed access to all 42 fields of a
    wbConnections CSV row. Score fields are stored as floats (defaulting to
    0.0), and all text fields default to empty strings.

    The to_row() and from_row() methods handle serialization to/from CSV rows,
    with defensive handling for:
      - Short rows (fewer than 42 columns, common in Spreadsheet exports)
      - Invalid float values (e.g., formula errors like "#REF!" in score cells)
      - Missing or whitespace-only fields
    """

    # --- Columns 0-7: Connection identity and description ---
    sender_cid: str                   # Col 0: Sender brain region Circuit ID
    scid_relation: str = ""           # Col 1: Sender region hierarchy relation
    notation_scid: str = ""           # Col 2: Region name as written in the paper
    receiver_cid: str = ""            # Col 3: Receiver brain region Circuit ID
    rcid_relation: str = ""           # Col 4: Receiver region hierarchy relation
    notation_rcid: str = ""           # Col 5: Region name as written in the paper
    size: str = ""                    # Col 6: Projection strength descriptor
    comments: str = ""                # Col 7: Free-text notes

    # --- Columns 8-16: Source literature metadata ---
    reference_id: str = ""            # Col 8:  "Author, YYYY" format citation
    taxon: str = ""                   # Col 9:  Experimental species
    measurement_method: str = ""      # Col 10: Technique used to observe the projection
    pointers_on_literature: str = ""  # Col 11: Page/section pointers
    pointers_on_figure: str = ""      # Col 12: Figure references
    in_depth_literature: str = ""     # Col 13: Additional references
    doc_link: str = ""                # Col 14: Document URL
    journal_name: str = ""            # Col 15: Journal name
    literature_type: str = ""         # Col 16: "Experimental results", "Review", etc.

    # --- Columns 17-19: Auto-generated display/search fields ---
    display_string: str = ""          # Col 17: Pre-formatted display string
    combined_search: str = ""         # Col 18: sender_cid + receiver_cid (for search)
    reference_id_bracket: str = ""    # Col 19: "[Author, YYYY]"

    # --- Columns 20-26: Credibility scores ---
    #
    # These 6 scores are multiplied together to produce the final CR.
    # All scores must be in the range [0.0, 1.0].
    # If any score is 0, the entire CR becomes 0.
    source_region_score: float = 0.0         # Col 20: Sender region identification accuracy
    receiver_region_score: float = 0.0       # Col 21: Receiver region identification accuracy
    citation_sentiment_index: float = 0.0    # Col 22: CSI — citation-based paper quality
    literature_type_score: float = 0.0       # Col 23: Score derived from literature type
    taxon_score: float = 0.0                 # Col 24: Species relevance score
    method_score_pder: float = 0.0           # Col 25: PDER — method's directional accuracy

    # --- Column 26-29: Credibility Rating (CR) variants ---
    credibility_rating: float = 0.0          # Col 26: CR = product of the 6 scores above
    summarized_cr: float = 0.0               # Col 27: Aggregated CR across same-projection records
    reviewed_cr: float = 0.0                 # Col 28: CR after expert review
    summarized_reviewed_cr: float = 0.0      # Col 29: Aggregated reviewed CR

    # --- Columns 30-41: Administrative/workflow fields ---
    contributor: str = ""             # Col 30: Who entered this data
    project_id: str = ""              # Col 31: Project identifier
    contributor_response: str = ""    # Col 32: Response to reviewer comments
    status: str = ""                  # Col 33: Workflow status
    review_results: str = ""          # Col 34: Reviewer's assessment
    auto_error_codes: str = ""        # Col 35: Auto-detected error codes
    error_code_1: str = ""            # Col 36: First error code
    error_code_2: str = ""            # Col 37: Second error code
    other_error_codes: str = ""       # Col 38: Additional error codes
    review_comments: str = ""         # Col 39: Free-text review comments
    reviewer: str = ""                # Col 40: Reviewer name
    reviewed_date: str = ""           # Col 41: Date of review

    def to_row(self) -> list:
        """
        Serialize this record to a CSV-compatible list of 42 strings.

        Score fields are formatted as strings. CR-related fields are rounded
        to 3 decimal places to match the precision used in the production
        database. This method is the inverse of from_row().

        Returns:
            A list of exactly 42 string values, one per CSV column.
        """
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
        """
        Construct a ConnectionRecord from a CSV row.

        Handles common data quality issues in Spreadsheet exports:
          - Rows shorter than 42 columns (trailing empty columns dropped)
          - Non-numeric values in score fields (e.g., "#REF!", "N/A")
          - Leading/trailing whitespace in text fields

        Args:
            row: A list of strings representing one CSV row. May have
                 fewer than 42 elements.

        Returns:
            A ConnectionRecord with all fields populated. Missing or
            invalid values are replaced with sensible defaults (empty
            string for text, 0.0 for scores).
        """
        def safe_float(val, default=0.0):
            """Parse a string as float, returning default on any failure."""
            try:
                return float(val.strip()) if val.strip() else default
            except (ValueError, AttributeError):
                return default

        def safe_str(idx):
            """Safely extract a string at the given index, handling short rows."""
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


# ============================================================================
# ReferenceRecord Dataclass
# ============================================================================

@dataclass
class ReferenceRecord:
    """
    A typed representation of a single row in wbReferences (23 columns).

    Only the first 13 columns are commonly used by this pipeline.
    The remaining columns (14-22) are review/workflow fields that are
    passed through unchanged.
    """
    reference_id: str = ""        # Col 0:  "Author, YYYY" format identifier
    doc: str = ""                 # Col 1:  Document link
    bib: str = ""                 # Col 2:  Bibliography entry
    doi: str = ""                 # Col 3:  DOI (required for Semantic Scholar API lookups)
    bibtex: str = ""              # Col 4:  BibTeX entry
    literature_type: str = ""     # Col 5:  "Experimental results", "Review", etc.
    article_type: str = ""        # Col 6:  Detailed article type
    authors: str = ""             # Col 7:  Author list
    title: str = ""               # Col 8:  Paper title
    journal: str = ""             # Col 9:  Journal name (used to populate wbConnections col 15)
    alternative_url: str = ""     # Col 10: Fallback URL when DOI is unavailable
    contributor: str = ""         # Col 11: Who registered this reference
    project_id: str = ""          # Col 12: Associated project ID

    @classmethod
    def from_row(cls, row: list) -> "ReferenceRecord":
        """
        Construct a ReferenceRecord from a CSV row.

        Same defensive handling as ConnectionRecord.from_row() for
        short rows and whitespace.
        """
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


# ============================================================================
# Validation Rules
# ============================================================================

class ValidationError:
    """
    Represents a single validation issue found in a record.

    Attributes:
        field:    The field name where the issue was found.
        message:  Human-readable description of the issue.
        severity: Either "error" (blocks pipeline) or "warning" (logged only).
    """
    def __init__(self, field: str, message: str, severity: str = "error"):
        self.field = field
        self.message = message
        self.severity = severity

    def __repr__(self):
        return f"[{self.severity.upper()}] {self.field}: {self.message}"


def validate_connection(rec: ConnectionRecord) -> list[ValidationError]:
    """
    Validate a ConnectionRecord against data integrity rules.

    Rules applied:
      1. Required fields: sender_cid, receiver_cid, reference_id must not be empty.
         Without these, the record cannot be meaningfully stored or queried.

      2. Reference ID format: Should match "Author, YYYY" (with optional accented
         characters and apostrophes like O'Brien or D'Angelo). Non-matching formats
         generate a warning (not an error) because some legacy records use non-standard
         formats.

      3. Score ranges: All 6 credibility score fields must be in [0.0, 1.0].
         Out-of-range scores would produce invalid CR values.

    Returns:
        A list of ValidationError objects. Empty list means the record is valid.
    """
    errors = []

    # Rule 1: Required fields — these form the primary key of a connection record
    if not rec.sender_cid:
        errors.append(ValidationError("sender_cid", "Sender CID is required"))
    if not rec.receiver_cid:
        errors.append(ValidationError("receiver_cid", "Receiver CID is required"))
    if not rec.reference_id:
        errors.append(ValidationError("reference_id", "Reference ID is required"))

    # Rule 2: Reference ID format check
    # Expected format: "Author, YYYY" (e.g., "Amaral, 1991", "O'Brien, 2019")
    # The regex allows accented Latin characters (À-ÿ) and apostrophes in names.
    # Known non-standard values like "author, year" and "#N/A" are exempted.
    if rec.reference_id:
        import re
        if not re.match(r'^[A-Za-zÀ-ÿ\'\-]+,\s*\d{4}$', rec.reference_id):
            if rec.reference_id not in ("author, year", "#N/A"):
                errors.append(ValidationError(
                    "reference_id",
                    f"Reference ID '{rec.reference_id}' should be 'Author, YYYY' format",
                    severity="warning"
                ))

    # Rule 3: All 6 credibility scores must be within [0.0, 1.0]
    # These scores are multiplied together to compute CR, so out-of-range
    # values would produce CRs greater than 1.0 or less than 0.0.
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
    """
    Validate a ReferenceRecord against data integrity rules.

    Rules applied:
      1. Required: reference_id must not be empty (it's the join key with wbConnections).
      2. Warning: at least one of DOI or alternative_url should be provided.
         DOI is needed for Semantic Scholar API lookups (CSI calculation),
         but older papers may lack DOIs, so this is a warning, not an error.

    Returns:
        A list of ValidationError objects.
    """
    errors = []

    if not rec.reference_id:
        errors.append(ValidationError("reference_id", "Reference ID is required"))
    if not rec.doi and not rec.alternative_url:
        errors.append(ValidationError(
            "doi",
            "Either DOI or alternative URL should be provided",
            "warning"
        ))

    return errors
