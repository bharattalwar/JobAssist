"""Match each job's employer to the sponsor allowlist.

This is the precision-critical stage: a false positive surfaces a job at an employer who won't
sponsor (wasted effort), while a false negative hides a real lifeline. Per the project's bias we
lean slightly toward recall but VISIBLY FLAG every non-exact match as unverified so it can be
confirmed by a human (see `verification_note`).

Every job's company name and every allowlist name pass through the SAME `normalize_company`
(after a light job-side cleaning of Adzuna junk), then:

  1. EXACT-normalized match             -> confidence 100, method "exact"        (trusted)
  2. Strong FUZZY (token_sort_ratio)    -> method "fuzzy"                         (UNVERIFIED)
  3. Subset FUZZY (token_set_ratio)     -> method "fuzzy-subset"                  (UNVERIFIED)
  4. otherwise                           -> method "none"                         (dropped)

Design notes:
  - Two fuzzy scorers: token_sort_ratio is length-sensitive so it MISSES short subset names
    ("meta" vs "meta platforms" ~= 44); token_set_ratio CATCHES those (~100) but is loose, so we
    only accept a token_set hit when the job's tokens are a genuine subset of the candidate's and
    share a DISTINCTIVE token (non-generic, >= MIN_TOKEN_LEN).
  - Highest-filings tiebreak: among candidates at/near the top score we pick the one with the most
    LCA filings, so "Amazon" -> "Amazon.com Services" [most filings] rather than an arbitrary
    Amazon subsidiary, and "Delta" -> "Delta Air Lines" rather than a tiny "Delta ..." company.
  - De-spaced variant: some brands are written run-together in the DOL data ("JPMorgan Chase").
    For initial-style names we also try the space-collapsed form ("jp morgan" -> "jpmorgan") and
    keep whichever variant matches better.
"""

import re

from rapidfuzz import fuzz, process

from jobassist.config import FUZZY_THRESHOLD
from jobassist.models import Job, MatchResult, SponsorRecord
from jobassist.normalize import normalize_company

# Ultra-generic company words that must NOT, by themselves, drive a fuzzy match.
GENERIC_TOKENS = {
    "solutions", "solution", "technologies", "technology", "systems", "system", "services",
    "service", "consulting", "consultants", "group", "global", "international", "associates",
    "partners", "company", "enterprises", "enterprise", "holdings", "holding", "labs",
    "laboratories", "software", "tech", "data", "digital", "america", "americas", "usa", "us",
    "na", "management", "ventures", "capital", "industries", "industrial", "networks", "network",
    "media", "online", "worldwide", "national", "general", "integrated", "information", "staffing",
    "resources", "corp", "corporation", "and", "of", "the", "com",
}

# A "distinctive" shared token (for subset matches) must be at least this long.
MIN_TOKEN_LEN = 4

# Method ranking for choosing the better of two candidate decisions.
_RANK = {"exact": 3, "fuzzy": 2, "fuzzy-subset": 1, "none": 0}

# --- #4 light name cleaning (Adzuna-side junk only) -------------------------
# Strip a trailing "- Glassdoor ...", "via LinkedIn ...", etc. Requires a separator or "via" before
# the site name so a real company literally named e.g. "ZipRecruiter" is never touched.
_SITE_TAIL = re.compile(
    r"\s*(?:[-–—|]|\bvia\b)\s*"
    r"(?:glassdoor|linkedin|indeed|dice|monster|careerbuilder|simplyhired|builtin|the\s*muse)\b.*$",
    re.IGNORECASE,
)
_RATING_TAIL = re.compile(r"\s+\d+\.\d+\s*$")  # trailing decimal rating like " 4.6"


def clean_company_name(raw: str) -> str:
    """Conservatively strip Adzuna junk (job-board suffixes / trailing ratings) from a raw name."""
    if not raw:
        return ""
    s = _SITE_TAIL.sub("", raw.strip())
    s = _RATING_TAIL.sub("", s)
    return s.strip()


def verification_note(method: str) -> str:
    """Human-facing verification label: exact matches are trusted, everything else needs a look."""
    return "verified" if method == "exact" else "UNVERIFIED — confirm"


def _best_by_filings(candidates: list, allowlist: dict[str, SponsorRecord], band: float = 1.0):
    """From (key, score, idx) tuples, keep those within `band` of the top score, pick most filings."""
    if not candidates:
        return None
    top = max(c[1] for c in candidates)
    near = [c for c in candidates if c[1] >= top - band]
    return max(near, key=lambda c: (allowlist[c[0]].filings, c[1]))


def _decide_for(norm: str, allowlist: dict[str, SponsorRecord], keys: list[str],
                threshold: float) -> tuple[SponsorRecord | None, float, str]:
    """Core decision for ONE normalized string: (sponsor, confidence, method)."""
    if not norm or len(norm) < 3:
        return (None, 0.0, "none")

    # 1. Exact-normalized match — fully trusted.
    rec = allowlist.get(norm)
    if rec is not None:
        return (rec, 100.0, "exact")

    # Precondition for ANY fuzzy: at least one distinctive (non-generic) token, so generic names
    # like "global tech solutions" never fuzzy-match some unrelated sponsor.
    tokens = norm.split()
    if not any(t not in GENERIC_TOKENS and len(t) >= 3 for t in tokens):
        return (None, 0.0, "none")

    # 2. Strong fuzzy: length-sensitive; a hit means the full names are genuinely close.
    #    limit=None returns ALL keys above the cutoff so the filings tiebreak sees every near-tie.
    cands = process.extract(norm, keys, scorer=fuzz.token_sort_ratio, score_cutoff=threshold, limit=None)
    best = _best_by_filings(cands, allowlist)
    if best:
        key, score, _ = best
        return (allowlist[key], float(score), "fuzzy")

    # 3. Subset fuzzy: short job name that is a guarded subset of a longer legal name.
    job_tokens = set(tokens)
    cands = process.extract(norm, keys, scorer=fuzz.token_set_ratio, score_cutoff=threshold, limit=None)
    passing = []
    for key, score, idx in cands:
        cand_tokens = set(key.split())
        shared = job_tokens & cand_tokens
        distinctive = [t for t in shared if t not in GENERIC_TOKENS and len(t) >= MIN_TOKEN_LEN]
        if job_tokens <= cand_tokens and distinctive:
            passing.append((key, score, idx))
    best = _best_by_filings(passing, allowlist)
    if best:
        key, score, _ = best
        return (allowlist[key], float(score), "fuzzy-subset")

    return (None, 0.0, "none")


def _pick_better(a: tuple, b: tuple) -> tuple:
    """Choose the stronger of two decisions: better method, then confidence, then filings."""
    if _RANK[b[2]] != _RANK[a[2]]:
        return b if _RANK[b[2]] > _RANK[a[2]] else a
    fa = a[0].filings if a[0] else -1
    fb = b[0].filings if b[0] else -1
    return b if (b[1], fb) > (a[1], fa) else a


def _decide(raw: str, allowlist: dict[str, SponsorRecord], keys: list[str],
            threshold: float) -> tuple[tuple[SponsorRecord | None, float, str], str]:
    """Decide a match for a raw company name; returns (decision, normalized_name_used)."""
    norm = normalize_company(clean_company_name(raw))
    best = _decide_for(norm, allowlist, keys, threshold)

    # 5. De-spaced variant for initial-style brands ("jp morgan" -> "jpmorgan" ~ "jpmorgan chase").
    #    Only when the leading token is short (initials/abbrev), to keep the blast radius tiny.
    if best[2] != "exact":
        tokens = norm.split()
        if len(tokens) >= 2 and len(tokens[0]) <= 3:
            despaced = "".join(tokens)
            if len(despaced) >= 4:
                best = _pick_better(best, _decide_for(despaced, allowlist, keys, threshold))

    return best, norm


def match_job(job: Job, allowlist: dict[str, SponsorRecord], keys: list[str],
              threshold: float = FUZZY_THRESHOLD) -> MatchResult:
    """Match a single job to the allowlist."""
    (sponsor, confidence, method), _norm = _decide(job.company_raw, allowlist, keys, threshold)
    return MatchResult(job=job, sponsor=sponsor, confidence=confidence, method=method)


def match_all(jobs: list[Job], allowlist: dict[str, SponsorRecord],
              threshold: float = FUZZY_THRESHOLD, keep_unmatched: bool = False) -> list[MatchResult]:
    """Match every job. By default drops method=='none' (precision bias); keep_unmatched=True keeps
    them so an audit can show the full picture. Decisions are cached per raw name so duplicate
    employers aren't re-scored against the ~30k allowlist."""
    keys = list(allowlist.keys())
    cache: dict[str, tuple[SponsorRecord | None, float, str]] = {}
    out: list[MatchResult] = []
    for job in jobs:
        if job.company_raw not in cache:
            cache[job.company_raw] = _decide(job.company_raw, allowlist, keys, threshold)[0]
        sponsor, confidence, method = cache[job.company_raw]
        if keep_unmatched or method != "none":
            out.append(MatchResult(job=job, sponsor=sponsor, confidence=confidence, method=method))
    return out
