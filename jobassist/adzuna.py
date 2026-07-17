"""Fetch recent US job postings from the Adzuna API.

We hit the public Adzuna search endpoint (JSON), pull only the fields we need into `Job` records,
and dedupe by Adzuna id across pages/queries. Two disciplines matter here:
  - Recency: request `max_days_old` so Adzuna only returns recent postings.
  - Budget: the free tier allows ~250 calls/day. A central call counter enforces a hard
    `max_calls` ceiling, and we stop gracefully (returning what we have) on any HTTP/network error.

`build_queries` (deriving searches from the resume) arrives in a later slice; for now callers pass
an explicit query list.
"""

import html
from datetime import date, datetime

import requests

from jobassist.config import ADZUNA_BASE_URL, MAX_API_CALLS, RESULTS_PER_PAGE
from jobassist.models import Job

# A broad catch-all is always searched: breadth is the whole point of this tool, and a senior
# resume's own titles (Staff/Principal/Architect) are too narrow to find enough transfer-capable jobs.
BROAD_CATCHALL = "software engineer"

# Title tokens too junior to spend the call budget on (kept in the ranking vocabulary, not queried).
_EXCLUDED_TITLE_TOKENS = {"analyst"}


def build_queries(titles: list[str], keywords: set[str] | None = None,
                  max_queries: int = 6) -> list[str]:
    """Turn resume titles into 3–6 Adzuna search queries.

    Always injects the broad catch-all first, then adds the resume's strongest titles, skipping
    early-career titles (e.g. "system analyst"). `--query` overrides this whole set upstream.
    """
    queries = [BROAD_CATCHALL]
    for title in titles:
        if len(queries) >= max_queries:
            break
        if any(tok in _EXCLUDED_TITLE_TOKENS for tok in title.split()):
            continue
        if title not in queries:
            queries.append(title)
    return queries


def _parse_date(value: object) -> date | None:
    """Parse an Adzuna ISO-8601 `created` string (e.g. '2026-07-01T12:00:00Z') to a date."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        return None


def _parse_job(raw: dict) -> Job:
    """Map one Adzuna result object to a Job, defensively (fields are occasionally missing)."""
    company = (raw.get("company") or {}).get("display_name") or ""
    location = (raw.get("location") or {}).get("display_name") or ""
    return Job(
        title=html.unescape((raw.get("title") or "").strip()),
        company_raw=company.strip(),
        location=location.strip(),
        posted=_parse_date(raw.get("created")),
        url=raw.get("redirect_url") or "",
        description=raw.get("description") or "",
        adzuna_id=str(raw.get("id") or ""),
    )


def fetch_jobs(
    app_id: str,
    app_key: str,
    queries: list[str],
    *,
    max_days_old: int,
    max_pages: int,
    location: str | None = None,
    results_per_page: int = RESULTS_PER_PAGE,
    max_calls: int = MAX_API_CALLS,
    dry_run: bool = False,
) -> tuple[list[Job], int]:
    """Fetch and dedupe jobs for the given queries. Returns (jobs, api_calls_used).

    dry_run fetches only page 1 of the first query (one API call) to validate creds/parsing cheaply.
    """
    if dry_run:
        queries = queries[:1]

    seen_ids: set[str] = set()
    jobs: list[Job] = []
    calls = 0

    for query in queries:
        pages = 1 if dry_run else max_pages
        for page in range(1, pages + 1):
            if calls >= max_calls:
                print(f"[budget] Reached MAX_API_CALLS={max_calls}; stopping fetch.")
                return jobs, calls

            params = {
                "app_id": app_id,
                "app_key": app_key,
                "results_per_page": results_per_page,
                "what": query,
                "max_days_old": max_days_old,
                "content-type": "application/json",
            }
            if location:
                params["where"] = location

            try:
                resp = requests.get(f"{ADZUNA_BASE_URL}/{page}", params=params, timeout=30)
                calls += 1
            except requests.RequestException as e:
                print(f"[adzuna] Network error on page {page} for {query!r}: {e}. Stopping fetch.")
                return jobs, calls

            if resp.status_code != 200:
                print(f"[adzuna] HTTP {resp.status_code} on page {page} for {query!r}. Stopping fetch.")
                return jobs, calls

            results = resp.json().get("results", [])
            if not results:
                break  # no (more) results for this query

            for raw in results:
                job = _parse_job(raw)
                if job.adzuna_id and job.adzuna_id in seen_ids:
                    continue
                seen_ids.add(job.adzuna_id)
                jobs.append(job)

            if len(results) < results_per_page:
                break  # last page for this query

    return jobs, calls
