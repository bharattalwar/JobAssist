"""Render the ranked results: a terminal digest and output/results.md.

Applies a per-employer cap so a single company's near-duplicate postings can't crowd out other
transfer-capable employers — the digest's job is to surface as many distinct DOORS as possible.
The cap runs AFTER ranking: keep each employer's best `PER_EMPLOYER_CAP` jobs, keep filling up to
`top_n` with other employers, and note "+N more openings" so nothing is silently lost.
"""

from collections import Counter
from datetime import date
from pathlib import Path

from jobassist.matcher import clean_company_name
from jobassist.models import MatchResult, RankedJob
from jobassist.normalize import normalize_company

PER_EMPLOYER_CAP = 2


def _emp_key(r: RankedJob) -> str:
    """Group jobs by the matched sponsor (falls back to the normalized company name)."""
    if r.match.sponsor:
        return r.match.sponsor.norm_name
    return normalize_company(clean_company_name(r.match.job.company_raw))


def cap_per_employer(ranked_all: list[RankedJob], top_n: int,
                     cap: int = PER_EMPLOYER_CAP) -> tuple[list[RankedJob], dict[str, int]]:
    """From the full ranked list, keep <=cap jobs per employer up to top_n. Returns (kept, extras)
    where extras[emp] is how many further openings that employer has beyond what was kept."""
    total = Counter(_emp_key(r) for r in ranked_all)
    kept: list[RankedJob] = []
    kept_count: Counter = Counter()
    for r in ranked_all:
        if len(kept) >= top_n:
            break
        key = _emp_key(r)
        if kept_count[key] < cap:
            kept.append(r)
            kept_count[key] += 1
    extras = {key: total[key] - kept_count[key] for key in kept_count}
    return kept, extras


def _annotate(kept: list[RankedJob], extras: dict[str, int]) -> list[tuple[RankedJob, str | None]]:
    """Pair each kept job with a '+N more' note, attached to that employer's last kept entry."""
    last_idx: dict[str, int] = {}
    for i, r in enumerate(kept):
        last_idx[_emp_key(r)] = i
    out = []
    for i, r in enumerate(kept):
        key = _emp_key(r)
        extra = extras.get(key, 0)
        note = f"+{extra} more opening(s) at this employer" if (i == last_idx[key] and extra > 0) else None
        out.append((r, note))
    return out


def _match_label(match: MatchResult, markdown: bool = False) -> str:
    """Human-facing sponsor-match label with a visible flag for non-exact matches."""
    if match.method == "exact":
        return "exact company match (verified)"
    flag = "**⚠ UNVERIFIED — confirm**" if markdown else "⚠ UNVERIFIED — confirm"
    return f"{match.method} match, confidence {match.confidence:.0f} — {flag}"


def print_results(kept: list[RankedJob], extras: dict[str, int]) -> None:
    """Print the terminal digest."""
    if not kept:
        print("\nNo jobs at transfer-capable employers were found for this run.")
        print("Try a broader --query, more --pages, or a wider --location.")
        return

    print(f"\nTop {len(kept)} openings at transfer-capable employers (max {PER_EMPLOYER_CAP} per employer):")
    for i, (r, note) in enumerate(_annotate(kept, extras), 1):
        m, j, sp = r.match, r.match.job, r.match.sponsor
        print(f"\n{i:>2}. [score {r.score}]  {j.title}")
        print(f"     {j.company_raw}  →  {sp.raw_name} [{sp.filings} H-1B LCAs, FY{sp.latest_year}]")
        print(f"     H-1B match: {_match_label(m)}")
        print(f"     {j.location or 'n/a'}  •  posted {j.posted or 'n/a'}")
        print(f"     apply: {j.url}")
        print(f"     why it fits: {r.why}")
        if note:
            print(f"     ({note})")


def write_markdown(kept: list[RankedJob], extras: dict[str, int], out_file: Path,
                   resume_name: str) -> None:
    """Write the readable output/results.md digest."""
    lines: list[str] = [
        "# jobAssist — H-1B-transfer job matches",
        "",
        f"_Resume: `{resume_name}` · {len(kept)} openings at transfer-capable employers "
        f"· generated {date.today().isoformat()}_",
        "",
        "> Employers below appear in **certified DOL H-1B (LCA) filings**, so they are able to file "
        "an H-1B transfer. Entries flagged **⚠ UNVERIFIED** are fuzzy company-name matches — confirm "
        "the employer identity before relying on them.",
        "",
    ]

    if not kept:
        lines.append("**No jobs at transfer-capable employers were found for this run.** "
                     "Try a broader `--query`, more `--pages`, or a wider `--location`.")
        out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return

    for i, (r, note) in enumerate(_annotate(kept, extras), 1):
        m, j, sp = r.match, r.match.job, r.match.sponsor
        lines += [
            f"## {i}. {j.title}",
            "",
            f"- **Company:** {j.company_raw} → **{sp.raw_name}** — {sp.filings} certified H-1B LCAs (FY{sp.latest_year})",
            f"- **H-1B match:** {_match_label(m, markdown=True)}",
            f"- **Location:** {j.location or 'n/a'} · **Posted:** {j.posted or 'n/a'}",
            f"- **Apply:** [Apply on Adzuna →]({j.url})",
            f"- **Why it fits:** {r.why}",
            f"- **Score:** {r.score}",
        ]
        if note:
            lines.append(f"- _{note}_")
        lines.append("")

    out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
