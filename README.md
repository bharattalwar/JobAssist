# jobAssist

Find recent US job postings at employers who can transfer your H-1B, ranked to your resume.

## What it does (and why it works)

If you already hold an H-1B, moving to a new employer needs an **H-1B transfer** — a cap-exempt
petition, *not* the lottery. The only employers who can do that are ones already set up to file
H-1Bs. jobAssist finds them:

1. It builds an allowlist of employers that appear in the **certified DOL H-1B (LCA) disclosure
   data** — i.e. employers who have demonstrably filed (and had certified) H-1B petitions, and are
   therefore able to file a transfer.
2. It pulls **recent US job postings** (last 14 days) from the Adzuna jobs API.
3. It keeps only postings whose **employer matches the allowlist**, then **ranks** them against your
   resume (skill/title overlap, with a small boost for employers that file more H-1Bs).
4. It prints a digest and writes `output/results.md`.

The result is a shortlist of live jobs at employers who can realistically sponsor your transfer.

## Prerequisites

- **Python 3.10+**
- **Free Adzuna API keys** — register at https://developer.adzuna.com/ and get an `app_id` +
  `app_key`.
- **The DOL LCA disclosure file** (`.xlsx`, ~100MB+):
  - Go to https://www.dol.gov/agencies/eta/foreign-labor/performance
  - Open the **"Disclosure Data"** tab
  - Download **"LCA Programs (H-1B, H-1B1, E-3)"**, the latest fiscal-year file
  - **Keep the original filename** — the fiscal year is parsed from it (e.g. `...FY2026...`).
- **A text-based resume PDF** (a real PDF with selectable text, not a scanned image).

## Setup

```bash
git clone <this-repo-url> jobAssist
cd jobAssist

python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# then edit .env and fill in:
#   ADZUNA_APP_ID=your_app_id
#   ADZUNA_APP_KEY=your_app_key
```

`.env` is git-ignored — your keys stay local.

## File placement

Put your two input files here (both directories are git-ignored, so nothing personal is committed):

```
data/lca/<the DOL LCA .xlsx>        e.g. data/lca/LCA_Disclosure_Data_FY2026_Q2.xlsx
data/resume/<your resume>.pdf       e.g. data/resume/jane-doe.pdf
```

## Run

```bash
python -m jobassist --resume "data/resume/your-resume.pdf"
```

First time? Do a cheap **dry run** (1 API call) to confirm your keys and files work end-to-end:

```bash
python -m jobassist --resume "data/resume/your-resume.pdf" --dry-run
```

### Flags

| Flag | Default | Meaning |
|------|---------|---------|
| `--resume PATH` | *(required)* | Path to your resume PDF. |
| `--query STR` | *auto* | Override the auto-derived searches with one explicit term (e.g. `"backend engineer"`). |
| `--location STR` | nationwide US | Narrow to a metro/state (e.g. `"San Francisco"`). |
| `--pages N` | 5 | Max Adzuna pages per query (50 results/page). |
| `--top N` | 25 | How many results to show/write. |
| `--threshold N` | 93 | Fuzzy company-match strictness (0–100; higher = stricter). |
| `--max-days N` | 14 | Recency window for postings. |
| `--lca-dir PATH` | `data/lca` | Alternate folder holding the DOL `.xlsx`. |
| `--dry-run` | off | Fetch only page 1 of one query (1 API call). |

By default the tool auto-derives its searches from your resume titles and always includes a broad
`"software engineer"` search for breadth. Use `--query` when you want to search one specific role.

## Output

- **Terminal:** a ranked digest of the top matches.
- **File:** `output/results.md` — the same list in readable Markdown (open it in any Markdown viewer).

Each entry shows the job title, company → matched sponsor, H-1B match confidence, location, posted
date, a working apply link, and a one-line "why it fits".

## How to read the output

- **"N certified H-1B LCAs"** — how many H-1B filings that employer has on record in the DOL data.
  Higher means the employer sponsors more often and is more practiced at it.
- **"⚠ UNVERIFIED — confirm"** — this employer was matched by a **fuzzy company-name match**, not an
  exact one. The name is close but not identical, so **confirm the employer's identity** (check the
  posting) before relying on it. Entries without this flag are exact matches and are trusted.
- **"+N more openings at this employer"** — the digest keeps at most **2 jobs per employer** so it
  can surface as many *distinct* transfer-capable employers as possible. This note tells you the
  employer has more openings you can find on their site or via the apply link.

## Limitations / honest caveats

- **LCA history shows an employer CAN and DOES sponsor — it is not a guarantee they will sponsor
  this particular role.** Always confirm sponsorship with the employer or recruiter.
- Only postings from the **last 14 days** are considered (whatever Adzuna currently indexes).
- The Adzuna **free tier is ~250 API calls/day**; the tool enforces a hard call budget per run.
- The DOL file is a **snapshot** — refresh it (drop in the newer FY file) roughly **quarterly** to
  keep the sponsor allowlist current.
- **Not in this version (possible future work):** a green-card/PERM sponsorship signal, direct ATS
  feeds (Greenhouse/Lever/Ashby), embeddings-based ranking, email digests, and scheduling.
