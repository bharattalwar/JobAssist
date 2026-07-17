"""Company-name normalization — the single shared contract between the allowlist and the matcher.

Both the DOL allowlist names and the Adzuna company names MUST pass through this exact function,
or a name that matched at build time would silently miss at query time. That is why this lives in
its own tiny, pure (no I/O) module with one implementation.

Strategy: lowercase -> replace any non-alphanumeric run (periods, punctuation, &, -) with a space
-> collapse runs of single-character tokens into one token (so dotted acronyms like "L.L.C." -> "llc"
and initials like "J.P." -> "jp", while "amazon.com" -> "amazon com" keeps "amazon" as a real token)
-> drop a leading "the" -> repeatedly drop trailing legal-entity suffix tokens -> collapse whitespace.
Returns "" for empty/junk input.
"""

import re

# Trailing legal-entity suffix tokens to strip. Dotted forms such as "L.L.C." / "Inc." reduce to
# these clean single tokens after the single-character-run collapse below.
LEGAL_SUFFIXES = {
    "inc", "incorporated",
    "corp", "corporation",
    "co", "company",
    "llc", "lc",
    "ltd", "limited",
    "lp", "llp", "lllp", "pllc", "plc", "pc",
    "na",  # "N.A." (national association), common for banks
}

# Anything that is not a lowercase letter or digit becomes a separator.
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _collapse_initials(tokens: list[str]) -> list[str]:
    """Join consecutive single-character tokens into one token.

    "l l c" -> "llc"  |  "j p morgan" -> "jp morgan"  |  "u s a" -> "usa"
    Multi-character tokens (e.g. "amazon", "com") are left untouched.
    """
    out: list[str] = []
    i = 0
    while i < len(tokens):
        if len(tokens[i]) == 1:
            run = []
            while i < len(tokens) and len(tokens[i]) == 1:
                run.append(tokens[i])
                i += 1
            out.append("".join(run))
        else:
            out.append(tokens[i])
            i += 1
    return out


def normalize_company(name: str) -> str:
    """Normalize a raw employer name to a canonical matching key.

    Examples:
        "Google LLC"                          -> "google"
        "Amazon.com Services, Inc."           -> "amazon com services"
        "Ernst & Young U.S. LLP"              -> "ernst young us"
        "The Coca-Cola Company"               -> "coca cola"
        ""                                    -> ""
    """
    if not name:
        return ""

    # Lowercase, then turn every run of non-alphanumeric characters into a single space.
    s = _NON_ALNUM.sub(" ", name.lower()).strip()
    if not s:
        return ""

    tokens = _collapse_initials(s.split())

    # Drop a leading article ("The Coca-Cola Company" -> "Coca-Cola Company").
    if len(tokens) > 1 and tokens[0] == "the":
        tokens = tokens[1:]

    # Repeatedly drop trailing legal-entity suffixes (handles e.g. "... co inc"), but never strip
    # away the whole name — keep at least one meaningful token.
    while len(tokens) > 1 and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()

    return " ".join(tokens)
