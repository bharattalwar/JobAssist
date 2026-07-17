"""Configuration: .env loading, filesystem paths, and tunable constants — all in one place."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Project root is the parent of this package directory.
PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent


@dataclass(frozen=True)
class Paths:
    lca_dir: Path       # DOL LCA .xlsx files live here (user-supplied, git-ignored)
    resume_dir: Path    # resume PDFs live here (user-supplied, git-ignored)
    output_dir: Path    # results written here (git-ignored)
    results_md: Path     # the markdown output file


PATHS = Paths(
    lca_dir=PROJECT_ROOT / "data" / "lca",
    resume_dir=PROJECT_ROOT / "data" / "resume",
    output_dir=PROJECT_ROOT / "output",
    results_md=PROJECT_ROOT / "output" / "results.md",
)

# ---- Tunable defaults (also exposed as CLI flags where it makes sense) ----
FUZZY_THRESHOLD = 93          # rapidfuzz score cutoff for a fuzzy company match (0–100)
TOP_N = 25                    # how many ranked jobs to show/write
MAX_DAYS_OLD = 14            # recency window for job postings
MAX_PAGES = 5                # max Adzuna pages fetched per query
RESULTS_PER_PAGE = 50        # Adzuna max page size
MAX_API_CALLS = 25          # hard global budget guard (well under the ~250/day free tier)

# Note: the LCA status filter (keep rows whose CASE_STATUS starts with "certified") lives in
# allowlist.py — a prefix check that is immune to hyphen/spacing differences across fiscal years.

ADZUNA_BASE_URL = "https://api.adzuna.com/v1/api/jobs/us/search"


def load_env() -> None:
    """Load ADZUNA_APP_ID / ADZUNA_APP_KEY from the project .env into the environment."""
    load_dotenv(PROJECT_ROOT / ".env")


def get_adzuna_creds() -> tuple[str, str]:
    """Return (app_id, app_key), or exit with a clear message if either is missing."""
    app_id = os.environ.get("ADZUNA_APP_ID", "").strip()
    app_key = os.environ.get("ADZUNA_APP_KEY", "").strip()
    if not app_id or not app_key:
        raise SystemExit(
            "Error: ADZUNA_APP_ID / ADZUNA_APP_KEY are not set. "
            "Copy .env.example to .env and fill them in (free keys: https://developer.adzuna.com/)."
        )
    return app_id, app_key


def ensure_dirs() -> None:
    """Create the data/output directories if they don't exist yet."""
    for d in (PATHS.lca_dir, PATHS.resume_dir, PATHS.output_dir):
        d.mkdir(parents=True, exist_ok=True)
