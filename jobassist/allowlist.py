"""Build the sponsor allowlist from DOL OFLC LCA disclosure data.

The allowlist is the heart of the tool: the set of employers with a recent H-1B filing history,
which we treat as evidence they are *transfer-capable*. We read the public DOL disclosure .xlsx
(placed by the user under data/lca/), keep only Certified / Certified - Withdrawn rows, take the
employer-name column, and normalize + dedupe into {norm_name: SponsorRecord}.

Two things make this tricky and drive the design:
  1. The file is 100MB+. We must NOT load every column into memory. We open the workbook in
     openpyxl's read-only streaming mode and pull only the two cells we need per row.
  2. Column headers vary by fiscal year (e.g. EMPLOYER_NAME vs LCA_CASE_EMPLOYER_NAME,
     CASE_STATUS vs STATUS). We detect the columns from the header row at runtime and fail loudly,
     printing the actual headers, if we can't find them.
"""

import re
from pathlib import Path

import openpyxl

from jobassist.models import SponsorRecord
from jobassist.normalize import normalize_company


def find_lca_files(lca_dir: Path) -> list[Path]:
    """Return the .xlsx files in the LCA directory (ignores temporary ~$ lock files)."""
    if not lca_dir.exists():
        return []
    return sorted(p for p in lca_dir.glob("*.xlsx") if not p.name.startswith("~$"))


def _norm_header(cell: object) -> str:
    """Canonicalize a header cell: lowercase, non-alphanumeric -> underscore."""
    if cell is None:
        return ""
    return re.sub(r"[^a-z0-9]+", "_", str(cell).lower()).strip("_")


def _find_column(norm_headers: list[str], exact: str, contains: list[str]) -> int | None:
    """Locate a column index: prefer an exact header match, then any header containing a hint."""
    for i, h in enumerate(norm_headers):
        if h == exact:
            return i
    for hint in contains:
        for i, h in enumerate(norm_headers):
            if hint in h:
                return i
    return None


def detect_columns(header_row: tuple) -> dict[str, int]:
    """Map the employer-name and case-status columns from a header row.

    Raises SystemExit (with the actual headers) if either column can't be found.
    """
    norm_headers = [_norm_header(c) for c in header_row]
    employer = _find_column(norm_headers, exact="employer_name", contains=["employer_name", "employer"])
    status = _find_column(norm_headers, exact="case_status", contains=["case_status", "status"])
    if employer is None or status is None:
        actual = ", ".join(str(c) for c in header_row)
        raise SystemExit(
            "Error: could not locate the EMPLOYER_NAME / CASE_STATUS columns in the DOL file.\n"
            f"Actual headers: {actual}"
        )
    return {"employer": employer, "status": status}


def _year_from_filename(path: Path) -> int:
    """Best-effort fiscal year from the filename (e.g. '...FY2024...' -> 2024). 0 if none.

    Used only for the small ranking boost, so a filename-based heuristic is sufficient.
    """
    m = re.search(r"(?:FY)?(20\d{2})", path.name)
    return int(m.group(1)) if m else 0


def build_allowlist(paths: list[Path]) -> tuple[dict[str, SponsorRecord], dict]:
    """Stream the given .xlsx files into {norm_name: SponsorRecord}, plus a stats dict.

    stats: files, rows_total, rows_certified, employers_unique, columns (per first file), header.
    """
    allow: dict[str, SponsorRecord] = {}
    rows_total = 0
    rows_certified = 0
    first_header: tuple = ()
    first_columns: dict[str, int] = {}

    for idx, path in enumerate(paths):
        year = _year_from_filename(path)
        # read_only + streaming: never materializes the whole 100MB+ sheet in memory.
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            ws = wb.active
            rows = ws.iter_rows(values_only=True)
            header = next(rows, None)
            if header is None:
                continue
            cols = detect_columns(header)
            emp_i, stat_i = cols["employer"], cols["status"]
            if idx == 0:
                first_header, first_columns = header, cols

            for row in rows:
                rows_total += 1
                # Rows can be short/ragged in read-only mode; guard index access.
                if stat_i >= len(row) or emp_i >= len(row):
                    continue
                status = row[stat_i]
                # Prefix check is immune to hyphen/spacing differences across fiscal years:
                # keeps "Certified" and "Certified - Withdrawn", excludes "Denied"/"Withdrawn".
                if status is None or not str(status).strip().lower().startswith("certified"):
                    continue
                rows_certified += 1
                raw = row[emp_i]
                if not raw:
                    continue
                norm = normalize_company(str(raw))
                if not norm:
                    continue
                rec = allow.get(norm)
                if rec is None:
                    allow[norm] = SponsorRecord(
                        raw_name=str(raw).strip(), norm_name=norm, filings=1, latest_year=year
                    )
                else:
                    rec.filings += 1
                    if year > rec.latest_year:
                        rec.latest_year = year
        finally:
            wb.close()

    stats = {
        "files": len(paths),
        "rows_total": rows_total,
        "rows_certified": rows_certified,
        "employers_unique": len(allow),
        "columns": first_columns,
        "header": first_header,
    }
    return allow, stats


def load_allowlist(lca_dir: Path) -> dict[str, SponsorRecord]:
    """Pipeline entry point: find the DOL .xlsx file(s) and build the allowlist."""
    files = find_lca_files(lca_dir)
    if not files:
        raise SystemExit(
            f"Error: no DOL LCA .xlsx found in {lca_dir}.\n"
            "Download the OFLC LCA disclosure file (H-1B) and place it there. "
            "See README / https://www.dol.gov/agencies/eta/foreign-labor/performance"
        )
    allow, _stats = build_allowlist(files)
    return allow


# ---------------------------------------------------------------------------
# Slice-1 checkpoint: `python -m jobassist.allowlist [path-to-xlsx-or-dir]`
# Prints the detected columns, counts, and a random sample so the data can be eyeballed.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import random
    import sys

    from jobassist import config

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else config.PATHS.lca_dir
    files = [target] if target.is_file() else find_lca_files(target)
    if not files:
        raise SystemExit(f"No .xlsx found at {target}")

    print(f"Files: {[str(p) for p in files]}")
    allow, stats = build_allowlist(files)
    header = stats["header"]
    cols = stats["columns"]
    print(f"\nDetected header ({len(header)} columns): {[str(h) for h in header]}")
    print(f"Column mapping: EMPLOYER -> index {cols.get('employer')} "
          f"({header[cols['employer']]!r}); STATUS -> index {cols.get('status')} "
          f"({header[cols['status']]!r})")
    print(f"\nRows read (excl. header):        {stats['rows_total']:,}")
    print(f"Rows Certified/Cert-Withdrawn:  {stats['rows_certified']:,}")
    print(f"Unique employers (deduped):     {stats['employers_unique']:,}")

    keys = list(allow.keys())
    random.seed(42)  # reproducible sample
    sample = random.sample(keys, min(20, len(keys)))
    print("\nRandom sample of 20 normalized sponsors (norm  <-  raw  [filings, latest FY]):")
    for k in sorted(sample):
        r = allow[k]
        print(f"  {k!r:<45} <- {r.raw_name!r:<45} [{r.filings}x, FY{r.latest_year}]")

    # Spot-check known sponsors (exact-normalized lookup).
    def _spot_check(title: str, names: list[str]) -> None:
        print(f"\n{title}")
        for name in names:
            key = normalize_company(name)
            hit = allow.get(key)
            mark = f"YES [{hit.filings}x, FY{hit.latest_year}]" if hit else "no"
            print(f"  {name:<42} -> {key!r:<40} {mark}")

    # Full legal names should resolve. Bare single-token brands may NOT — that's the
    # single-token brand gap we address in Slice 3's matcher; surfacing it now on purpose.
    _spot_check("Known-sponsor spot check — FULL legal names (expect YES):", [
        "Google LLC", "Amazon.com Services LLC", "Cognizant Technology Solutions US Corp",
        "Infosys Limited", "Microsoft Corporation", "Meta Platforms, Inc.",
    ])
    _spot_check("Known-sponsor spot check — BARE brand names (may be 'no' pre-matcher):", [
        "Meta", "Stripe", "Nvidia", "Databricks", "Google", "Amazon",
    ])
