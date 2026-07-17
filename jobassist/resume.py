"""Parse a resume PDF into ranking keywords and job titles.

Two outputs feed the rest of the pipeline:
  - extract_keywords(text) -> the full skill/title vocabulary used to RANK jobs (overlap with the
    job title + description).
  - extract_titles(text)   -> the ordered job-title phrases used to BUILD Adzuna queries (Slice 5).

Design choice: keyword extraction is dictionary-driven (a curated skill list + a guarded title
heuristic) rather than free n-gram extraction. That keeps the output clean — no ligature/garbage
tokens, and no contact/PII (name, email, phone) leaking in as "skills".
"""

import re
from pathlib import Path

import pdfplumber

# ---------------------------------------------------------------------------
# Curated skill dictionary: canonical term -> surface variants to look for (lowercased).
# Matching is whole-token (symbol-aware), so "c++"/"c#"/".net" work and "go" won't hit "google".
# ---------------------------------------------------------------------------
SKILLS: dict[str, list[str]] = {
    # Languages
    "java": ["java"], "python": ["python"], "go": ["golang"], "javascript": ["javascript", "js"],
    "typescript": ["typescript", "ts"], "c++": ["c++"], "c#": ["c#"], "scala": ["scala"],
    "kotlin": ["kotlin"], "ruby": ["ruby"], "php": ["php"], "rust": ["rust"], "swift": ["swiftui", "swift ui"],
    "sql": ["sql"], "bash": ["bash", "shell"],
    # Frameworks / runtimes
    "spring": ["spring boot", "spring"], "hibernate": ["hibernate"], "react": ["react", "react.js"],
    "angular": ["angular"], "vue": ["vue", "vue.js"], "node": ["node.js", "nodejs", "node"],
    "django": ["django"], "flask": ["flask"], ".net": [".net", "asp.net", "dotnet"],
    "express": ["express.js", "express"], "rails": ["ruby on rails"],
    # Infra / cloud / devops
    "aws": ["aws", "amazon web services"], "gcp": ["gcp", "google cloud"], "azure": ["azure"],
    "kubernetes": ["kubernetes", "k8s"], "docker": ["docker"], "terraform": ["terraform"],
    "kafka": ["kafka"], "rabbitmq": ["rabbitmq"], "redis": ["redis"], "elasticsearch": ["elasticsearch"],
    "ci/cd": ["ci/cd", "cicd", "ci cd"], "jenkins": ["jenkins"], "grpc": ["grpc"],
    # Databases
    "postgresql": ["postgresql", "postgres"], "mysql": ["mysql"], "mongodb": ["mongodb", "mongo"],
    "dynamodb": ["dynamodb"], "cassandra": ["cassandra"], "oracle": ["oracle"], "snowflake": ["snowflake"],
    # Architecture / concepts
    "microservices": ["microservices", "microservice"], "api": ["api", "apis"], "rest": ["rest", "restful"],
    "graphql": ["graphql"], "distributed systems": ["distributed systems"],
    "event-driven": ["event-driven", "event driven"], "oauth": ["oauth"], "saml": ["saml"],
    "soa": ["soa"], "etl": ["etl"], "spark": ["apache spark"], "airflow": ["airflow"],
    # Domain: payments / billing / commerce
    "payments": ["payments", "payment"], "billing": ["billing"], "subscriptions": ["subscriptions", "subscription"],
    "checkout": ["checkout"], "monetization": ["monetization", "monetisation"], "cards": ["card", "cards"],
    "fraud": ["fraud"], "ledger": ["ledger"], "invoicing": ["invoicing", "invoice"],
    "pci": ["pci", "pci-dss", "pci dss"], "tokenization": ["tokenization", "tokenisation"],
    "settlement": ["settlement", "settlements"], "reconciliation": ["reconciliation"],
    "e-commerce": ["e-commerce", "ecommerce"], "stripe": ["stripe"], "paypal": ["paypal"],
    # Practices
    "agile": ["agile"], "scrum": ["scrum"], "tdd": ["tdd"], "ci": ["continuous integration"],
}

# Title building blocks.
ROLE_NOUNS = {"engineer", "developer", "architect", "manager", "lead", "analyst",
              "consultant", "administrator", "specialist", "programmer", "scientist"}
TITLE_MODIFIERS = {
    "software", "senior", "staff", "principal", "lead", "junior", "backend", "back", "frontend",
    "front", "full", "fullstack", "stack", "platform", "data", "cloud", "systems", "system", "web",
    "mobile", "application", "applications", "solutions", "solution", "devops", "site", "reliability",
    "security", "infrastructure", "payments", "payment", "billing", "integration", "integrations",
    "distributed", "machine", "learning", "api", "embedded", "firmware", "network", "database",
    "quality", "test", "automation", "engineering", "technical", "tech", "product", "services",
    "microservices",
}

# ---- PII scrubbing (never surface these as keywords) ----
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
_URL = re.compile(r"https?://\S+|www\.\S+")


def _strip_pii(s: str) -> str:
    return _URL.sub(" ", _PHONE.sub(" ", _EMAIL.sub(" ", s)))


def _contains(text: str, phrase: str) -> bool:
    """Whole-token match that tolerates symbols (c++, c#, .net, ci/cd)."""
    pat = r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])"
    return re.search(pat, text) is not None


def extract_text(path: str | Path) -> str:
    """Extract text from a resume PDF. Exits with a clear message on any failure (no traceback)."""
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise SystemExit(f"Error: resume PDF not found at '{path}'. Place your resume under data/resume/.")
    try:
        parts: list[str] = []
        with pdfplumber.open(p) as pdf:
            for page in pdf.pages:
                parts.append(page.extract_text() or "")  # guard None pages
    except Exception as e:  # noqa: BLE001 — surface a friendly message, not a traceback
        raise SystemExit(f"Error: could not read PDF '{path}': {e}")
    text = "\n".join(parts).strip()
    if not text:
        raise SystemExit(
            f"Error: no text extracted from '{path}'. It may be a scanned/image-only PDF; "
            "please provide a text-based PDF."
        )
    return text


def extract_titles(text: str) -> list[str]:
    """Ordered, de-duplicated job-title phrases (role noun + preceding known modifiers)."""
    tokens = re.findall(r"[a-z]+", text.lower())
    titles: list[str] = []
    seen: set[str] = set()
    for i, tok in enumerate(tokens):
        if tok not in ROLE_NOUNS:
            continue
        mods: list[str] = []
        j = i - 1
        while j >= 0 and len(mods) < 3 and tokens[j] in TITLE_MODIFIERS:
            mods.insert(0, tokens[j])
            j -= 1
        if mods:  # skip bare role nouns and (crucially) "Firstname Engineer" name artifacts
            phrase = " ".join(mods + [tok])
            if phrase not in seen:
                seen.add(phrase)
                titles.append(phrase)
    return titles


def extract_keywords(text: str) -> set[str]:
    """The full ranking vocabulary: curated skills + multi-word title phrases (no PII).

    Bare seniority tokens (senior/staff/principal/lead/junior) are deliberately EXCLUDED: they carry
    no domain signal, so a "Staff Engineer" title would otherwise bank points from "staff" AND
    "staff engineer" and let domain-irrelevant roles (e.g. mechanical "Staff Engineer") outrank real
    matches. The meaningful multi-word phrases ("staff engineer", "principal solution architect")
    are kept via extract_titles.
    """
    low = _strip_pii(text.lower())
    keywords: set[str] = set()
    for canonical, variants in SKILLS.items():
        if any(_contains(low, v) for v in variants):
            keywords.add(canonical)
    keywords.update(extract_titles(text))
    return keywords


# ---------------------------------------------------------------------------
# Slice-4 checkpoint: `python -m jobassist.resume [path-to-pdf]`
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    from jobassist import config

    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
    else:
        pdfs = sorted(config.PATHS.resume_dir.glob("*.pdf"))
        if not pdfs:
            raise SystemExit(f"No resume PDF found in {config.PATHS.resume_dir}")
        target = pdfs[0]

    print(f"Resume: {target}\n")
    text = extract_text(target)

    print("=" * 80)
    print("1) First 15 lines of raw extracted text")
    print("=" * 80)
    for line in text.splitlines()[:15]:
        print(f"  | {line}")

    keywords = extract_keywords(text)
    titles = extract_titles(text)

    print("\n" + "=" * 80)
    print("2) Job titles (feed Slice-5 queries)")
    print("=" * 80)
    for t in titles:
        print(f"  - {t}")

    print("\n" + "=" * 80)
    print("3) Sorted extracted keyword set (feeds ranking)")
    print("=" * 80)
    for k in sorted(keywords):
        print(f"  {k}")
    print(f"\nKeyword count: {len(keywords)}")
