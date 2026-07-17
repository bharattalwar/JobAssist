# jobAssist — Requirements

## 1. Problem

A software professional on an H1B visa has been laid off. He **already holds H1B** and has an
**approved I-140**, but his green-card priority date is **not current**. To keep working in the US he
needs a new employer to file an **H1B transfer** (a cap-exempt petition — *not* the H1B lottery).

The single most important property of a target employer is therefore: **is this employer capable of
transferring an H1B?** In practice that means the employer has a **recent history of H1B filings**. A
job at an employer with no sponsorship history is useless to him no matter how well it fits his skills.

Manually checking every job posting's employer against sponsorship data is slow and error-prone.
`jobAssist` automates it: it cross-references live US job postings against public H1B filing data and
returns a **ranked shortlist of jobs at transfer-capable employers**, matched to his resume.

## 2. Goals

- Produce a **ranked list of current US job openings** (last 14 days) whose employer has a **recent
  H1B filing history** (transfer-capable).
- Rank those jobs by **fit to the user's resume** (skill/title keyword overlap), with a small boost
  for the employer's H1B filing recency/volume.
- **Bias for precision** — it is better to omit a borderline employer than to surface a job at an
  employer unlikely to sponsor.
- Print the shortlist to the terminal **and** write it to a readable `output/results.md`.
- Run **once on demand and exit**. Fast to a usable result. Simple, readable, commented code.

## 3. No-goals (explicitly out of v1)

- No green-card / PERM signal (a *later* nice-to-have — employer sponsorship is v1-only).
- No ATS feeds (Greenhouse/Lever/Ashby), no embeddings-based ranking.
- No email, no scheduling, no web server, no database.
- **No scraping** of LinkedIn, Indeed, or aggregator sites. Legitimate sources only.
- No third-party data harvesting — the only resume used is the user's own (consented).

## 4. Functional requirements

1. **Sponsor allowlist** — Build a normalized, deduplicated set of transfer-capable employers from the
   **DOL OFLC LCA disclosure data** (H-1B), a public `.xlsx` the user downloads into `data/lca/`.
   - Filter to `CASE_STATUS ∈ {Certified, Certified - Withdrawn}`.
   - Use the employer-name column; column headers vary by fiscal year, so **detect them at runtime**.
   - Track, per employer, a **filing count** and the **latest fiscal year** seen (for the ranking boost).
2. **Job fetch** — Fetch US job postings from the **Adzuna API**
   (`https://api.adzuna.com/v1/api/jobs/us/search/{page}`), JSON, `max_days_old=14`.
   - Auto-derive 3–6 focused search queries from the resume; `--query` overrides with an explicit term.
   - Nationwide US by default; `--location` narrows.
   - Respect the free tier (~250 calls/day): default ~5 pages × 50 results, hard call budget, graceful stop.
3. **Company matching** — For each job, match `company.display_name` to the allowlist:
   - **Normalize** both sides identically (lowercase, strip legal suffixes Inc/LLC/Corp/Ltd/Co/…, strip
     punctuation, collapse whitespace).
   - **Exact-normalized** match first; else **rapidfuzz** fuzzy match at a tunable threshold (~90).
   - Tag each result with **match method** (exact/fuzzy) and **confidence**. Drop unmatched jobs.
4. **Resume parsing** — Parse a resume **PDF** (path via CLI arg, under `data/resume/`) with pdfplumber
   and extract a set of **skill/title keywords** for ranking.
5. **Ranking** — Score each matched job by **keyword overlap** between the resume and the job's
   title+description, plus a **small, capped boost** for the employer's H1B filing recency/volume.
6. **Output** — Print the **top N** ranked jobs to the terminal and write them to `output/results.md`.
   Each entry: title, company, location, posted date, apply link, H1B-match confidence, one-line "why it fits".

## 5. Non-functional requirements

- **Stack:** Python 3 in a venv. Deps: `pandas, requests, rapidfuzz, pdfplumber, python-dotenv, openpyxl`.
- **Efficiency:** the DOL file is 100MB+ — stream it, reading only the two needed columns; never load all
  columns into memory.
- **Secrets:** Adzuna credentials live in a **git-ignored `.env`** (`ADZUNA_APP_ID`, `ADZUNA_APP_KEY`),
  loaded via python-dotenv. A committed `.env.example` documents the keys with blank values.
- **Privacy:** the DOL file, the resume, and `output/` are git-ignored and never committed.
- **Runtime:** single on-demand invocation; no persistent process.

## 6. Inputs / outputs

**Inputs**
- DOL OFLC LCA disclosure `.xlsx` in `data/lca/` (user-downloaded).
- Resume PDF path (CLI `--resume`, file under `data/resume/`).
- Adzuna credentials in `.env`.
- CLI flags (see §8).

**Outputs**
- Terminal: a ranked table of the top N jobs.
- File: `output/results.md` — one markdown section per job with the fields listed in FR6.

## 7. Business rules

- An employer is **transfer-capable** iff it appears in the allowlist (has a Certified / Certified -
  Withdrawn LCA on record). Only such jobs are surfaced.
- **Precision over recall:** exact-normalized matches are fully trusted (confidence 100); fuzzy matches
  must clear the threshold and are visibly flagged; very short / single-token normalized names skip fuzzy
  matching to avoid spurious hits.
- Recency window is **14 days** (Adzuna `max_days_old` / the posting's `created` date).
- The employer H1B boost is **small and capped** — it must not outweigh genuine resume relevance.

## 8. CLI

```
python -m jobassist --resume PATH [options]
  --resume PATH       (required) resume PDF under data/resume/
  --query STR         override the auto-derived search query
  --location STR      narrow to a metro/state (default: nationwide US)
  --pages N           max Adzuna pages per query (default 5)
  --top N             number of results to show/write (default 25)
  --threshold N       fuzzy match threshold 0–100 (default 90)
  --max-days N        recency window in days (default 14)
  --lca-dir PATH      override data/lca location
  --dry-run           fetch page 1 of a single query only (protects API budget)
```

## 9. Edge cases

- No `.xlsx` in `data/lca/`, or unreadable file → clear error, exit non-zero.
- DOL headers don't match expected columns → fail loudly, print the actual header list.
- Resume PDF missing / unreadable / yields empty text → clear error.
- pdfplumber returns `None` for a page → treat as empty string, continue.
- Adzuna 429 / non-200 / network error → stop gracefully, proceed with whatever was collected.
- Adzuna returns zero jobs, or zero jobs match the allowlist → report clearly, write an empty-but-valid file.
- Missing/blank Adzuna credentials → clear error before any network call.
- `data/lca/`, `data/resume/`, `output/` don't exist → created at runtime.

## 10. Error handling

- Fail fast with a **human-readable message** (not a traceback) for the expected failures above; exit non-zero.
- Network/API issues are **non-fatal**: log, stop fetching, continue the pipeline with partial data.
- Never print secrets.

## 11. Acceptance criteria

1. Given a real DOL `.xlsx`, the tool prints the detected column mapping, raw/filtered/deduped counts, and a
   sample of normalized sponsor names; known large sponsors (e.g. Google, Amazon, Cognizant, Infosys) are present.
2. Given valid `.env` creds, a fixed query returns parsed `Job` records with title/company/location/date/url.
3. Matching produces an auditable table of company_raw → normalized → method → confidence → matched sponsor,
   with no obviously-wrong fuzzy matches at the default threshold.
4. Given a real resume PDF, the extracted keyword set is sensible (real skills/titles, no extraction garbage).
5. End-to-end, `output/results.md` contains a ranked list with all required fields and working apply links,
   and the ordering reflects resume relevance (H1B boost does not dominate).
6. Total Adzuna calls for a default run stay within the free-tier budget.

## 12. Validation strategy

- **Slice-by-slice checkpoints:** after each build slice, print the key data (counts + samples) and eyeball it
  before proceeding — correctness lives in the data, not just in passing code.
- **Allowlist:** spot-check known sponsors present, names normalized/deduped, report row count.
- **Matching:** review a sample of matched vs unmatched companies to judge precision; tune the threshold.
- **End-to-end:** run against the real resume + a real Adzuna call and inspect the actual results file.
- **Budget-safe iteration:** use `--dry-run` for a single cheap API call while developing.
