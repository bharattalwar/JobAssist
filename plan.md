# jobAssist — Build Plan

Build **one slice at a time**. After each slice, **STOP and show the key OUTPUT** (counts + samples),
because this tool's correctness lives in its data. Code stays simple, readable, and commented.

## Architecture at a glance

Flat package `jobassist/`, run via `python -m jobassist`.

```
cli.main
  config.load_env / get_adzuna_creds
  allowlist.load_allowlist(lca_dir)     -> dict[norm_name -> SponsorRecord]
  resume.extract_text/extract_keywords  -> set[str] resume_kw
  adzuna.build_queries(resume_kw)       -> list[str]   (or [--query])
  adzuna.fetch_jobs(...)                -> list[Job]
  matcher.match_all(jobs, allowlist)    -> list[MatchResult]   (via SHARED normalize)
  ranker.rank(matches, resume_kw, top)  -> list[RankedJob]
  report.print_results + write_markdown -> terminal + output/results.md
```

`normalize.normalize_company` is the single shared contract between `allowlist` and `matcher`. If the
two ever normalize differently, names that matched at build time silently miss at query time — so it is
its own module with one implementation.

## Modules

| Module | Responsibility |
|---|---|
| `models.py` | dataclasses: `SponsorRecord`, `Job`, `MatchResult`, `RankedJob` |
| `config.py` | `.env` load, paths, tunable constants (threshold, top_n, statuses, legal suffixes) |
| `normalize.py` | `normalize_company(name) -> str` (shared) |
| `allowlist.py` | DOL `.xlsx` → `{norm_name: SponsorRecord}` (stream, detect columns) |
| `adzuna.py` | `build_queries()` + `fetch_jobs()` → `list[Job]` (call budget, graceful stop) |
| `resume.py` | PDF → keyword `set[str]` |
| `matcher.py` | `Job` → `MatchResult` (exact/fuzzy/none + confidence) |
| `ranker.py` | `MatchResult` → `RankedJob` (score + "why") |
| `report.py` | print top N + write `output/results.md` |
| `cli.py` | argparse + orchestration |

## Slices

### Slice 0 — Docs + scaffold
- **Do:** write `requirements.md` + `plan.md` (**stop for review**). Then create venv, install the 6 deps,
  write `requirements.txt`, `.env.example`, the package skeleton, `models.py`, `config.py`, `normalize.py`.
- **Validates:** environment works on Python 3.14 (all wheels install); normalization is correct.
- **Test:** `python -m jobassist --help` prints usage; deps import; run `normalize_company` on ~8 hand-picked
  names — e.g. `Google LLC → google`, `Amazon.com Services, Inc. → amazon.com services`,
  `COGNIZANT TECHNOLOGY SOLUTIONS US CORP → cognizant technology solutions us`.

### Slice 1 — Allowlist from DOL `.xlsx`
- **Do:** `allowlist.py` — detect header columns (case-insensitive substring), stream rows with openpyxl
  `read_only`, filter Certified statuses, normalize + dedupe, aggregate filing count + latest FY.
- **Validates:** the core allowlist is correct — the first data-correctness gate.
- **Test:** print detected column mapping, rows read, count after status filter, count after normalize+dedupe,
  and a random sample of 20 normalized names. **Spot-check** big sponsors present; normalization looks sane.

### Slice 2 — Adzuna fetch (fixed query)
- **Do:** `adzuna.py` `fetch_jobs()` with a hardcoded query (e.g. "software engineer"); parse
  `company.display_name`, location, `created` date, `redirect_url`; dedupe by id; central call counter.
- **Validates:** creds, endpoint, `max_days_old=14`, JSON parsing, dedupe, budget guard.
- **Test:** print #API calls used, #jobs fetched, and 5 raw parsed `Job` records.

### Slice 3 — Matcher
- **Do:** `matcher.py` — exact-normalized (conf 100) → rapidfuzz `token_sort_ratio` with `score_cutoff`;
  skip fuzzy for very short/single-token names; keep only matched jobs.
- **Validates:** match precision at the default threshold.
- **Test:** table of every job → {company_raw, normalized, method, confidence, matched sponsor}; verify a few
  exact + fuzzy; check for spurious fuzzy hits; report exact/fuzzy/none counts. **Tune threshold here.**

### Slice 4 — Resume parsing
- **Do:** `resume.py` — pdfplumber text extraction (guard `None` pages) + keyword extraction (curated skill
  dictionary + title/n-gram heuristics, stopword-filtered).
- **Validates:** resume yields sensible skills/titles, no PDF garbage.
- **Test:** print the sorted extracted keyword set from the real resume PDF.

### Slice 5 — Queries-from-resume + ranking
- **Do:** `adzuna.build_queries(resume_kw)` (3–6 focused, title-led queries) replacing the hardcoded query;
  `ranker.py` — overlap score + small capped H1B boost + "why" string.
- **Validates:** ranking order is intuitive; the boost stays subordinate to relevance.
- **Test:** print top N `RankedJob` with score, overlapping terms, and "why".

### Slice 6 — Report / output + full wiring
- **Do:** `report.py` (`print_results`, `write_markdown`) + complete `cli.main` orchestration + arg parsing.
- **Validates:** end-to-end output is correct and readable.
- **Test:** terminal top-N table **and** `output/results.md`; open the `.md`, verify fields + working apply links.

### Final — README.md
- **Do:** write run instructions for a non-author (Manish): what it does, prerequisites (Python, Adzuna keys,
  the DOL file + where to download it, a resume PDF), setup (venv, pip install, `.env`), the run command, and
  where output lands.

## Build order

`0 → 1 → 2 → 3 → 4 → 5 → 6 → README`, stopping after each for output review.

## Verification commands

```bash
# Slice 0
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt
python -m jobassist --help
python -c "from jobassist.normalize import normalize_company as n; \
  print([n(x) for x in ['Google LLC','Amazon.com Services, Inc.','COGNIZANT TECHNOLOGY SOLUTIONS US CORP']])"

# Slice 1 (needs a DOL .xlsx in data/lca/)
python -m jobassist._probe allowlist        # or a small __main__ hook that prints counts + sample

# Slice 2 (needs .env creds)
python -m jobassist --resume data/resume/<name>.pdf --dry-run

# End-to-end (needs DOL file + resume PDF)
python -m jobassist --resume data/resume/<name>.pdf
open output/results.md
```

(Exact probe/checkpoint invocations are finalized per slice; each simply prints the slice's key output.)

## Risks & mitigations

1. **100MB+ `.xlsx`.** Stream via `openpyxl.load_workbook(read_only=True, data_only=True)` +
   `iter_rows(values_only=True)`; read header first, pull only the 2 needed cells/row; never build a full
   DataFrame. Fail loudly listing actual headers if columns aren't found.
2. **Fuzzy false positives.** Exact first; `token_sort_ratio` + `score_cutoff`; skip short/single-token names;
   tag method+confidence; drop `none`; visibly flag lower-confidence fuzzy.
3. **Resume→query.** Derive 3–6 focused title-led queries, not one keyword-stuffed query; ranker does precision;
   `--query` overrides.
4. **Rate budget.** Central call counter + hard `max_pages`/global cap; `results_per_page=50`; `--dry-run`;
   graceful stop + partial return on 429/non-200.
