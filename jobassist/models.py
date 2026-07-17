"""Typed data containers passed between pipeline stages.

Kept as plain dataclasses so the output of every slice is easy to print and eyeball.
"""

from dataclasses import dataclass
from datetime import date


@dataclass
class SponsorRecord:
    """One transfer-capable employer, aggregated from the DOL LCA data."""

    raw_name: str        # a representative employer name as it appeared in the DOL file
    norm_name: str       # normalized key used for matching (see normalize.normalize_company)
    filings: int = 0     # number of certified LCAs seen for this employer
    latest_year: int = 0 # most recent fiscal year seen (0 if unknown) — feeds the ranking boost


@dataclass
class Job:
    """One job posting fetched from Adzuna."""

    title: str
    company_raw: str          # Adzuna company.display_name, unmodified
    location: str
    posted: date | None       # parsed from Adzuna `created`; None if missing/unparseable
    url: str                  # apply/redirect link
    description: str
    adzuna_id: str            # used to dedupe across pages/queries


@dataclass
class MatchResult:
    """A job paired with the allowlist employer it matched (if any)."""

    job: Job
    sponsor: SponsorRecord | None
    confidence: float         # 0–100
    method: str               # "exact" | "fuzzy" | "none"


@dataclass
class RankedJob:
    """A matched job with its resume-fit score and a one-line explanation."""

    match: MatchResult
    score: float
    why: str
