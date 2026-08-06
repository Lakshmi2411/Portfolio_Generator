"""
Phase 3: Technical deep scan.

Phase 1 already collected each repo's dependency/manifest files
(requirements.txt, package.json, pyproject.toml, etc.) but nothing has used
them until now. This phase parses those files and cross-references the
actual libraries against a curated tech dictionary, so the portfolio can
say what a project REALLY uses — not just what its README happened to
mention.

Motivating example (real, from this project's own testing): a repo's README
said "chat with your PDF using an LLM," but its requirements.txt revealed
langchain, chromadb, sentence-transformers, and faiss-cpu — meaning it's
actually a hybrid dense+sparse RAG pipeline with vector search, not just "a
chatbot." Phase 4 needs that distinction to write an accurate, impressive
project description.

Purely deterministic — no LLM calls, no API usage, no cost. It's just
parsing text that Phase 1 already fetched.
"""

import json
import re
import sys
from typing import Optional

try:
    import tomllib  # stdlib in Python 3.11+
except ImportError:
    tomllib = None


# ---------- curated tech dictionary ----------
# package/import name (lowercase, as it appears in a manifest) -> (display name, category)
# Deliberately curated rather than exhaustive: a raw requirements.txt from
# `pip freeze` is 80%+ transitive noise (urllib3, certifi, idna, six...).
# Only packages that represent a genuine, nameable technology choice are
# worth surfacing on a portfolio.
TECH_DICTIONARY = {
    # LLM orchestration / agent frameworks
    "crewai": ("CrewAI", "LLM Orchestration"),
    "crewai-tools": ("CrewAI Tools", "LLM Orchestration"),
    "langchain": ("LangChain", "LLM Orchestration"),
    "langchain-core": ("LangChain", "LLM Orchestration"),
    "langchain-community": ("LangChain", "LLM Orchestration"),
    "langchain-classic": ("LangChain", "LLM Orchestration"),
    "langchain-text-splitters": ("LangChain", "LLM Orchestration"),
    "langgraph": ("LangGraph", "LLM Orchestration"),
    "langsmith": ("LangSmith", "LLM Orchestration"),
    "llama-index": ("LlamaIndex", "LLM Orchestration"),
    "semantic-kernel": ("Semantic Kernel", "LLM Orchestration"),
    "instructor": ("Instructor", "LLM Orchestration"),
    "mcp": ("Model Context Protocol (MCP)", "LLM Orchestration"),
    # LLM providers / SDKs
    "openai": ("OpenAI API", "LLM Provider"),
    "groq": ("Groq API", "LLM Provider"),
    "google-generativeai": ("Gemini API", "LLM Provider"),
    "anthropic": ("Anthropic API", "LLM Provider"),
    "cohere": ("Cohere API", "LLM Provider"),
    # Vector search / retrieval
    "chromadb": ("ChromaDB", "Vector Database"),
    "faiss-cpu": ("FAISS", "Vector Search"),
    "faiss-gpu": ("FAISS", "Vector Search"),
    "pinecone-client": ("Pinecone", "Vector Database"),
    "weaviate-client": ("Weaviate", "Vector Database"),
    "qdrant-client": ("Qdrant", "Vector Database"),
    "rank-bm25": ("BM25", "Sparse/Keyword Retrieval"),
    "rank_bm25": ("BM25", "Sparse/Keyword Retrieval"),
    # Embeddings / NLP
    "sentence-transformers": ("Sentence Transformers", "Embeddings"),
    "transformers": ("Hugging Face Transformers", "NLP/ML"),
    "tokenizers": ("Hugging Face Tokenizers", "NLP/ML"),
    "spacy": ("spaCy", "NLP"),
    "nltk": ("NLTK", "NLP"),
    # Classic ML / data science
    "scikit-learn": ("scikit-learn", "Machine Learning"),
    "torch": ("PyTorch", "Deep Learning"),
    "tensorflow": ("TensorFlow", "Deep Learning"),
    "keras": ("Keras", "Deep Learning"),
    "xgboost": ("XGBoost", "Machine Learning"),
    "lightgbm": ("LightGBM", "Machine Learning"),
    "pandas": ("Pandas", "Data Analysis"),
    "numpy": ("NumPy", "Data Analysis"),
    "scipy": ("SciPy", "Data Analysis"),
    # Data visualization
    "matplotlib": ("Matplotlib", "Data Visualization"),
    "seaborn": ("Seaborn", "Data Visualization"),
    "plotly": ("Plotly", "Data Visualization"),
    "altair": ("Altair", "Data Visualization"),
    # Web frameworks / APIs
    "fastapi": ("FastAPI", "Web Framework"),
    "flask": ("Flask", "Web Framework"),
    "django": ("Django", "Web Framework"),
    "starlette": ("Starlette", "Web Framework"),
    "uvicorn": ("Uvicorn (ASGI)", "Web Framework"),
    "gunicorn": ("Gunicorn", "Web Framework"),
    # Cloud / infra
    "boto3": ("AWS SDK (boto3)", "Cloud/AWS"),
    "botocore": ("AWS SDK (boto3)", "Cloud/AWS"),
    # Databases
    "sqlalchemy": ("SQLAlchemy", "Database"),
    "psycopg2": ("PostgreSQL (psycopg2)", "Database"),
    "pymongo": ("MongoDB (pymongo)", "Database"),
    "redis": ("Redis", "Database"),
    # Testing
    "pytest": ("pytest", "Testing"),
    "unittest2": ("unittest", "Testing"),
    "tox": ("tox", "Testing"),
    "coverage": ("Coverage.py", "Testing"),
    # Document processing
    "pypdf": ("pypdf", "Document Processing"),
    "pymupdf": ("PyMuPDF", "Document Processing"),
    "pdfplumber": ("pdfplumber", "Document Processing"),
    "python-docx": ("python-docx", "Document Processing"),
    "openpyxl": ("openpyxl", "Document Processing"),
    "python-pptx": ("python-pptx", "Document Processing"),
    # Search tools
    "tavily-python": ("Tavily Search API", "Web Search Tool"),
    "duckduckgo-search": ("DuckDuckGo Search", "Web Search Tool"),
    "duckduckgo_search": ("DuckDuckGo Search", "Web Search Tool"),
    # UI / apps
    "streamlit": ("Streamlit", "App Framework"),
    "gradio": ("Gradio", "App Framework"),
    # JS/frontend (from package.json)
    "react": ("React", "Frontend"),
    "next": ("Next.js", "Frontend"),
    "vue": ("Vue.js", "Frontend"),
    "express": ("Express", "Backend (Node)"),
    "axios": ("Axios", "HTTP Client"),
}


# ---------- prose keyword dictionary (for work experience, not package manifests) ----------
# Job descriptions name cloud services, protocols, and practices that never
# appear as an installable package (e.g. "AWS Step Functions" isn't a pip
# package name) — this is a separate, phrase-based dictionary matched via
# substring search over free text rather than manifest parsing.
PROSE_TECH_DICTIONARY = {
    "aws lambda": ("AWS Lambda", "Cloud/AWS"),
    "step functions": ("AWS Step Functions", "Cloud/AWS"),
    "eventbridge": ("Amazon EventBridge", "Cloud/AWS"),
    "cloudwatch": ("Amazon CloudWatch", "Cloud/AWS"),
    "sqs": ("Amazon SQS", "Cloud/AWS"),
    "sns": ("Amazon SNS", "Cloud/AWS"),
    "s3": ("Amazon S3", "Cloud/AWS"),
    "ec2": ("Amazon EC2", "Cloud/AWS"),
    "dynamodb": ("DynamoDB", "Cloud/AWS"),
    "api gateway": ("AWS API Gateway", "Cloud/AWS"),
    "azure": ("Microsoft Azure", "Cloud/Azure"),
    "gcp": ("Google Cloud Platform", "Cloud/GCP"),
    "google cloud": ("Google Cloud Platform", "Cloud/GCP"),
    "openapi": ("OpenAPI/Swagger", "API Design"),
    "swagger": ("OpenAPI/Swagger", "API Design"),
    "rest api": ("REST APIs", "API Design"),
    "graphql": ("GraphQL", "API Design"),
    "microservices": ("Microservices Architecture", "System Design"),
    "docker": ("Docker", "DevOps"),
    "kubernetes": ("Kubernetes", "DevOps"),
    "terraform": ("Terraform", "DevOps"),
    "ci/cd": ("CI/CD Pipelines", "DevOps"),
    "github actions": ("GitHub Actions", "DevOps"),
    "jenkins": ("Jenkins", "DevOps"),
    "unit test": ("Unit Testing", "Testing"),
    "integration test": ("Integration Testing", "Testing"),
    "bdd": ("BDD Testing", "Testing"),
    "test coverage": ("Test Coverage", "Testing"),
    "code review": ("Code Review Practices", "Engineering Practice"),
    "distributed system": ("Distributed Systems", "System Design"),
    "concurrency": ("Concurrency Control", "System Design"),
    "fault tolerance": ("Fault-Tolerant Design", "System Design"),
    "retry logic": ("Retry/Resilience Patterns", "System Design"),
    "low level design": ("System Design (LLD)", "System Design"),
    "cross-account": ("Cross-Account AWS Access", "Cloud/AWS"),
    "devops": ("DevOps Collaboration", "DevOps"),
    "monitoring": ("Production Monitoring", "Operations"),
}


def scan_work_experience_text(jobs: list) -> list:
    """
    Applies the same evidence-first philosophy Phase 3 uses for repos, but to
    work experience text (Phase 2 output): only surfaces technologies that are
    literally named in what the person wrote about their own role, rather than
    letting Phase 4 infer or embellish. Deliberately simple substring matching
    over PROSE_TECH_DICTIONARY — no LLM call needed for this, since it's exact
    phrase detection, not summarization or judgment.

    Also applies a few narrow co-occurrence rules for patterns flat substring
    matching misses in natural prose:
      - "Lambda" and "AWS" mentioned separately in the same text (e.g. "AWS...
        Built a Lambda-based service") rather than as the exact phrase "AWS Lambda"
      - conjunctive testing lists like "unit, integration, end-to-end testing" or
        "100% coverage", where the noun ("testing"/"coverage") isn't repeated
        after each qualifier the way a flat phrase match like "unit test" expects
    """
    results = []
    for job in jobs:
        text = (
            f"{job.get('description', '')} {job.get('job_description') or ''}".lower()
        )
        detected = []
        seen = set()

        def add(display_name, category):
            if display_name not in seen:
                detected.append({"name": display_name, "category": category})
                seen.add(display_name)

        for phrase, (display_name, category) in PROSE_TECH_DICTIONARY.items():
            if phrase in text:
                add(display_name, category)

        # Co-occurrence: "lambda" + "aws" anywhere in text, even if not glued together
        if "lambda" in text and "aws" in text:
            add("AWS Lambda", "Cloud/AWS")

        # Co-occurrence: testing qualifiers sharing one "test/coverage" mention
        # in a conjunctive list, rather than each repeating "test" individually
        if re.search(r"\btest(ing)?\b", text) or "coverage" in text:
            if "unit" in text:
                add("Unit Testing", "Testing")
            if "integration" in text:
                add("Integration Testing", "Testing")
            if "end-to-end" in text or "e2e" in text:
                add("End-to-End Testing", "Testing")
            if "coverage" in text:
                add("Test Coverage", "Testing")

        results.append(
            {
                "company": job.get("company"),
                "title": job.get("title"),
                "detected_stack": sorted(
                    detected, key=lambda d: (d["category"], d["name"])
                ),
            }
        )
    return results


# ---------- dependency file parsers ----------


def parse_requirements_txt(content: str) -> set:
    """Extract package names from a requirements.txt (handles ==, >=, extras, etc.)."""
    names = set()
    for line in content.splitlines():
        line = line.strip().lstrip("\ufeff")  # strip BOM some files had
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # Strip version specifiers and extras: "package[extra]==1.2.3" -> "package"
        match = re.match(r"^([A-Za-z0-9._-]+)", line)
        if match:
            names.add(match.group(1).lower())
    return names


def parse_package_json(content: str) -> set:
    """Extract package names from dependencies + devDependencies in package.json."""
    names = set()
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return names
    for section in ("dependencies", "devDependencies"):
        for pkg_name in (data.get(section) or {}).keys():
            names.add(pkg_name.lower())
    return names


def parse_pyproject_toml(content: str) -> set:
    """Extract package names from [project.dependencies] or [tool.poetry.dependencies]."""
    names = set()

    if tomllib is not None:
        try:
            data = tomllib.loads(content)
            for dep in data.get("project", {}).get("dependencies") or []:
                match = re.match(r"^([A-Za-z0-9._-]+)", dep)
                if match:
                    names.add(match.group(1).lower())
            poetry_deps = (
                data.get("tool", {}).get("poetry", {}).get("dependencies") or {}
            )
            for pkg_name in poetry_deps.keys():
                if pkg_name.lower() != "python":
                    names.add(pkg_name.lower())
            return names
        except Exception:
            pass  # fall through to regex fallback below

    # Regex fallback (covers most common formats without needing tomllib)
    for match in re.finditer(
        r'"([A-Za-z0-9._-]+)(?:\[[^\]]*\])?(?:[><=!~][^"]*)?"', content
    ):
        names.add(match.group(1).lower())
    return names


DEPENDENCY_PARSERS = {
    "requirements.txt": parse_requirements_txt,
    "package.json": parse_package_json,
    "pyproject.toml": parse_pyproject_toml,
    "Pipfile": parse_requirements_txt,  # close enough format-wise for name extraction
}


def extract_package_names(dependency_files: dict) -> set:
    """Runs every dependency file through its parser, returns the union of package names."""
    all_names = set()
    for filename, content in (dependency_files or {}).items():
        parser = DEPENDENCY_PARSERS.get(filename)
        if parser and content:
            all_names.update(parser(content))
    return all_names


# ---------- tech detection + README cross-check ----------


def detect_technologies(package_names: set) -> list:
    """Matches extracted package names against the curated dictionary."""
    detected = []
    seen_display_names = set()
    for pkg in package_names:
        if pkg in TECH_DICTIONARY:
            display_name, category = TECH_DICTIONARY[pkg]
            if (
                display_name not in seen_display_names
            ):  # dedupe e.g. langchain-core + langchain-community
                detected.append({"name": display_name, "category": category})
                seen_display_names.add(display_name)
    return sorted(detected, key=lambda d: (d["category"], d["name"]))


def find_hidden_tech(detected: list, readme_text: str) -> list:
    """
    Tech that's genuinely present (via dependency files) but NOT mentioned
    anywhere in the README — this is exactly the "PDF chatbot that's secretly
    a hybrid RAG pipeline" case Phase 4 needs flagged, so the generated
    project description doesn't undersell what was actually built.
    """
    readme_lower = (readme_text or "").lower()
    hidden = []
    for tech in detected:
        name_lower = tech["name"].lower()
        # Check both "sentence transformers" and "sentence-transformers" — READMEs
        # often use the package's hyphenated form while our display names use spaces.
        variants = {
            name_lower,
            name_lower.replace(" ", "-"),
            name_lower.replace("-", " "),
        }
        if not any(v in readme_lower for v in variants):
            hidden.append(tech)
    return hidden


def flag_shared_environment_noise(
    all_scans: list, noise_threshold: float = 0.5
) -> None:
    """
    Mutates each scan's detected_stack/hidden_tech entries in place, adding an
    "environment_wide" flag: True if this technology shows up in more than
    `noise_threshold` fraction of scanned repos that have ANY dependency files.

    Why this matters: a requirements.txt from `pip freeze` on a SHARED virtual
    environment (used across many unrelated projects) lists every package
    installed in that env, not just what the specific project imports. If
    "LangChain" shows up as "detected" in five completely different projects
    including ones whose own README says "built from scratch, no framework,"
    that's a strong signal it's environment noise, not a genuine per-project
    choice — and Phase 4 should not confidently claim a project "uses X" on
    that basis alone. Technologies unique to one or two repos are far more
    likely to reflect a real, deliberate choice for that specific project.
    """
    scans_with_deps = [s for s in all_scans if s["raw_package_count"] > 0]
    if not scans_with_deps:
        return

    tech_repo_count = {}
    for scan in scans_with_deps:
        for tech in scan["detected_stack"]:
            tech_repo_count[tech["name"]] = tech_repo_count.get(tech["name"], 0) + 1

    threshold_count = noise_threshold * len(scans_with_deps)

    for scan in all_scans:
        for tech_list in (scan["detected_stack"], scan["hidden_tech"]):
            for tech in tech_list:
                count = tech_repo_count.get(tech["name"], 0)
                tech["environment_wide"] = count > threshold_count


def scan_repo(repo: dict) -> dict:
    """Runs the full technical scan for a single repo (as stored in Phase 1's JSON)."""
    package_names = extract_package_names(repo.get("dependency_files"))
    detected = detect_technologies(package_names)
    hidden = find_hidden_tech(detected, repo.get("readme_text"))

    return {
        "name": repo["name"],
        "languages": list((repo.get("languages") or {}).keys()),
        "detected_stack": detected,
        "hidden_tech": hidden,  # real but unmentioned in README — surface these prominently in Phase 4
        "raw_package_count": len(package_names),
    }


# ---------- orchestration ----------


def run_phase3(
    profile_json_path: str,
    phase2_json_path: Optional[str] = None,
    output_path: str = "phase3_output.json",
) -> dict:
    with open(profile_json_path, "r", encoding="utf-8") as f:
        profile_data = json.load(f)
    repos = {r["name"]: r for r in profile_data["repos"]}

    # Scope the scan to featured repos if a Phase 2 output is given, else scan everything.
    target_names = list(repos.keys())
    work_experience = []
    if phase2_json_path:
        with open(phase2_json_path, "r", encoding="utf-8") as f:
            phase2_data = json.load(f)
        target_names = (
            phase2_data.get("featured_repo_names")
            or phase2_data.get("selected_repo_names")
            or target_names
        )
        work_experience = phase2_data.get("work_experience") or []

    results = []
    for name, repo in repos.items():
        results.append(scan_repo(repo))

    # Frequency-based noise detection needs a broad sample to be reliable —
    # compute it across the person's FULL repo history (all repos in Phase 1's
    # data), not just the 10 featured ones, then filter down to the target
    # set for the final printed/saved output.
    flag_shared_environment_noise(results)
    results = [r for r in results if r["name"] in set(target_names)]
    results.sort(key=lambda r: target_names.index(r["name"]))

    for scan in results:
        distinctive = [
            t for t in scan["detected_stack"] if not t.get("environment_wide")
        ]
        noisy = [t for t in scan["detected_stack"] if t.get("environment_wide")]

        print(f"{scan['name']}:")
        if distinctive:
            print(
                f"  Distinctive tech (trust these): {', '.join(t['name'] for t in distinctive)}"
            )
        if noisy:
            print(
                f"  Also present but common across your repos (verify before claiming): "
                f"{', '.join(t['name'] for t in noisy)}"
            )
        if not scan["detected_stack"]:
            print("  (no dependency files / nothing matched)")

        hidden_distinctive = [
            t for t in scan["hidden_tech"] if not t.get("environment_wide")
        ]
        if hidden_distinctive:
            print(
                f"  -> genuinely hidden (in deps, not in README, and distinctive): "
                f"{', '.join(t['name'] for t in hidden_distinctive)}"
            )

    work_experience_stack = scan_work_experience_text(work_experience)
    if work_experience_stack:
        print("\nWork experience:")
        for job_scan in work_experience_stack:
            tech_names = (
                ", ".join(t["name"] for t in job_scan["detected_stack"])
                or "(no known tech phrases detected)"
            )
            print(f"  {job_scan['title']} at {job_scan['company']}: {tech_names}")

    output = {"repos": results, "work_experience_stack": work_experience_stack}
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"\nSaved Phase 3 output to {output_path}")
    return output


if __name__ == "__main__":
    profile_path = (
        sys.argv[1]
        if len(sys.argv) > 1
        else input("Path to Phase 1 JSON file: ").strip()
    )
    phase2_path = sys.argv[2] if len(sys.argv) > 2 else None
    if phase2_path is None:
        answer = input(
            "Path to Phase 2 JSON file (Enter to scan all repos instead): "
        ).strip()
        phase2_path = answer or None
    run_phase3(profile_path, phase2_path)
