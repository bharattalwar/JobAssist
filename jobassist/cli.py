"""Command-line interface and full pipeline orchestration.

    load env -> ensure dirs -> load allowlist -> parse resume -> build queries -> fetch Adzuna
    -> match to allowlist -> rank -> per-employer cap -> print + write output/results.md
"""

import argparse
from pathlib import Path

from jobassist import config
from jobassist.adzuna import build_queries, fetch_jobs
from jobassist.allowlist import load_allowlist
from jobassist.matcher import match_all
from jobassist.ranker import rank
from jobassist.report import cap_per_employer, print_results, write_markdown
from jobassist.resume import extract_keywords, extract_text, extract_titles


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Define and parse the CLI arguments."""
    p = argparse.ArgumentParser(
        prog="jobassist",
        description="Find recent US jobs at employers likely to transfer your H1B, ranked to your resume.",
    )
    p.add_argument("--resume", metavar="PATH",
                   help="path to your resume PDF (under data/resume/). Required for a full run.")
    p.add_argument("--query", metavar="STR", default=None,
                   help="override the search query auto-derived from your resume.")
    p.add_argument("--location", metavar="STR", default=None,
                   help="narrow to a metro/state (default: nationwide US).")
    p.add_argument("--pages", type=int, default=config.MAX_PAGES,
                   help=f"max Adzuna pages per query (default {config.MAX_PAGES}).")
    p.add_argument("--top", type=int, default=config.TOP_N,
                   help=f"number of results to show/write (default {config.TOP_N}).")
    p.add_argument("--threshold", type=int, default=config.FUZZY_THRESHOLD,
                   help=f"fuzzy company-match threshold 0–100 (default {config.FUZZY_THRESHOLD}).")
    p.add_argument("--max-days", type=int, default=config.MAX_DAYS_OLD,
                   help=f"recency window in days (default {config.MAX_DAYS_OLD}).")
    p.add_argument("--lca-dir", metavar="PATH", default=None,
                   help="override the data/lca directory holding the DOL .xlsx.")
    p.add_argument("--dry-run", action="store_true",
                   help="fetch only page 1 of a single query (protects the API budget).")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the full pipeline. Returns a process exit code."""
    args = parse_args(argv)
    config.load_env()
    config.ensure_dirs()

    # --- Fail fast on missing inputs before the expensive allowlist load ---
    if not args.resume:
        raise SystemExit("Error: --resume is required. Pass the path to your resume PDF (under data/resume/).")
    app_id, app_key = config.get_adzuna_creds()   # exits clearly if creds are missing

    # --- Resume -> ranking vocabulary + query titles ---
    resume_text = extract_text(args.resume)
    resume_kw = extract_keywords(resume_text)
    titles = extract_titles(resume_text)
    queries = [args.query] if args.query else build_queries(titles, resume_kw)

    # --- Sponsor allowlist from the DOL file (streams ~1M rows) ---
    lca_dir = Path(args.lca_dir) if args.lca_dir else config.PATHS.lca_dir
    print(f"Loading sponsor allowlist from {lca_dir} ...")
    allowlist = load_allowlist(lca_dir)
    print(f"  {len(allowlist):,} transfer-capable employers loaded.")

    # --- Fetch recent US jobs ---
    scope = args.location or "nationwide US"
    print(f"Searching Adzuna ({scope}, last {args.max_days}d) for: {', '.join(repr(q) for q in queries)}")
    jobs, calls = fetch_jobs(
        app_id, app_key, queries,
        max_days_old=args.max_days, max_pages=args.pages,
        location=args.location, dry_run=args.dry_run,
    )
    print(f"  {calls} API call(s) used; {len(jobs)} recent jobs fetched.")

    # --- Match -> rank -> per-employer cap ---
    matches = match_all(jobs, allowlist, threshold=args.threshold, keep_unmatched=False)
    ranked_all = rank(matches, resume_kw)
    kept, extras = cap_per_employer(ranked_all, args.top)
    print(f"  {len(matches)} jobs at transfer-capable employers; showing top {len(kept)}.")

    # --- Output: terminal + file ---
    print_results(kept, extras)
    write_markdown(kept, extras, config.PATHS.results_md, resume_name=Path(args.resume).name)
    print(f"\nWrote digest to {config.PATHS.results_md}")
    return 0
