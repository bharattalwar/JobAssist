"""Rank matched jobs by fit to the resume.

Score = resume-keyword overlap with the job's title + description (title matches weighted higher),
plus a SMALL, CAPPED boost for the employer's H-1B filing volume/recency. The boost is deliberately
bounded below the value of a single title-keyword match, so it can break near-ties between similarly
relevant jobs but can NEVER outrank a job that genuinely fits the resume better.
"""

import math

from jobassist.models import MatchResult, RankedJob
# Reuse the resume's symbol-aware token matcher so "c++"/"ci/cd"/multi-word terms match identically.
from jobassist.resume import _contains as _term_in_text

# Overlap weights: a title hit is worth more than a description hit.
TITLE_WEIGHT = 5.0
DESC_WEIGHT = 1.0

# H-1B boost cap. Kept < TITLE_WEIGHT on purpose: one extra title-keyword match (5.0) always beats
# the entire boost range (<= 3.0), so employer volume never overtakes real resume relevance.
MAX_H1B_BOOST = 3.0
_VOLUME_REF = 5000  # ~ a top-tier sponsor's filing count, for log-normalizing volume to [0, 1]


def matched_terms(match: MatchResult, resume_kw: set[str]) -> tuple[set[str], set[str]]:
    """Return (terms found in the job TITLE, terms found in the job DESCRIPTION)."""
    title_l = match.job.title.lower()
    desc_l = match.job.description.lower()
    title_hits = {kw for kw in resume_kw if _term_in_text(title_l, kw)}
    desc_hits = {kw for kw in resume_kw if _term_in_text(desc_l, kw)}
    return title_hits, desc_hits


def _h1b_boost(match: MatchResult, newest_fy: int) -> float:
    """Small capped boost from filing volume (log-scaled) and recency (relative to newest FY seen)."""
    sponsor = match.sponsor
    if not sponsor or sponsor.filings <= 0:
        return 0.0
    volume = min(1.0, math.log10(1 + sponsor.filings) / math.log10(1 + _VOLUME_REF))
    if newest_fy and sponsor.latest_year:
        recency = max(0.0, 1.0 - 0.25 * max(0, newest_fy - sponsor.latest_year))
    else:
        recency = 1.0
    return MAX_H1B_BOOST * (0.7 * volume + 0.3 * recency)


def _why(title_hits: set[str], desc_hits: set[str], match: MatchResult) -> str:
    """One-line 'why it fits', naming the overlapping resume terms (title matches called out)."""
    total = len(title_hits | desc_hits)
    if total == 0:
        return "No direct resume-term overlap; surfaced by your title search."
    parts = []
    if title_hits:
        parts.append("title: " + ", ".join(sorted(title_hits)))
    extra = sorted(desc_hits - title_hits)
    if extra:
        parts.append("skills: " + ", ".join(extra[:8]))
    return f"Matches {total} resume terms — " + "; ".join(parts)


def score_job(match: MatchResult, resume_kw: set[str], newest_fy: int = 0) -> RankedJob:
    """Score one matched job and build its RankedJob."""
    title_hits, desc_hits = matched_terms(match, resume_kw)
    base = TITLE_WEIGHT * len(title_hits) + DESC_WEIGHT * len(desc_hits - title_hits)
    score = base + _h1b_boost(match, newest_fy)
    return RankedJob(match=match, score=round(score, 2), why=_why(title_hits, desc_hits, match))


def rank(matches: list[MatchResult], resume_kw: set[str], top_n: int | None = None) -> list[RankedJob]:
    """Score and sort all matched jobs (highest first). Returns all when top_n is None — the
    per-employer cap in report.py needs the full ranked list to fill diversity and count extras."""
    newest_fy = max((m.sponsor.latest_year for m in matches if m.sponsor), default=0)
    ranked = [score_job(m, resume_kw, newest_fy) for m in matches]
    ranked.sort(key=lambda r: r.score, reverse=True)
    return ranked if top_n is None else ranked[:top_n]
