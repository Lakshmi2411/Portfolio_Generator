"""
Phase 4: Content generation.

Takes the outputs of Phase 1 (raw repo data), Phase 2 (roles, featured repos,
work experience), and Phase 3 (detected tech, noise-filtered confidence) and
writes the actual portfolio content: a bio, one description per featured
project, and a consolidated skills summary.

ANTI-HALLUCINATION GUARDRAIL (same pattern as the user's own
ai-resume-cover-letter project): the model is explicitly instructed to only
reference technologies, achievements, and facts that are literally present
in the grounding data it's given — never to invent metrics, employers,
dates, or capabilities. Skills summary is computed deterministically (no LLM
involved) for that reason — aggregation doesn't need judgment, so keeping it
out of the LLM's hands removes a whole class of possible fabrication.

Only two LLM calls total (one for all project blurbs, one for the bio) to
keep this cheap on free-tier token budgets, regardless of how many featured
repos there are.
"""

import json
import sys
from typing import Optional

from llm_client import LLMClient, LLMError

README_EXCERPT_LEN = (
    1000  # more generous than Phase 2's 300 — content quality matters more here
)
# than ranking-prompt token economy


# ---------- grounding data assembly ----------


def build_repo_content_brief(repo: dict, tech_scan: Optional[dict]) -> dict:
    """Bundles everything Phase 4 is allowed to draw from for one repo."""
    readme = repo.get("readme_text") or ""
    distinctive = []
    hidden = []
    if tech_scan:
        distinctive = [
            t["name"]
            for t in tech_scan.get("detected_stack", [])
            if not t.get("environment_wide")
        ]
        hidden = [
            t["name"]
            for t in tech_scan.get("hidden_tech", [])
            if not t.get("environment_wide")
        ]
    return {
        "name": repo["name"],
        "description": repo.get("description") or "",
        "readme_excerpt": readme[:README_EXCERPT_LEN],
        "languages": list((repo.get("languages") or {}).keys()),
        "distinctive_tech": distinctive,  # confidently real, project-specific — safe to headline
        "hidden_tech": hidden,  # real but README doesn't say so — worth surfacing explicitly
    }


# ---------- project descriptions (one batched LLM call) ----------

PROJECT_DESC_SYSTEM_PROMPT = """You are an expert technical writer producing portfolio project
descriptions for a job-seeking developer.

CRITICAL GROUNDING RULE: only reference technologies, features, and capabilities that are
explicitly present in the "readme_excerpt", "distinctive_tech", or "hidden_tech" fields you are
given for each project. NEVER invent metrics (e.g. "processed 10,000 requests/sec"), user counts,
company names, or capabilities not stated in the provided data. If the source material is thin,
write a shorter, honest description rather than padding it with invented specifics.

For each project, write a 2-4 sentence description that:
- States what the project actually does (from readme_excerpt)
- Explicitly names distinctive_tech and hidden_tech where relevant — these are real, verified
  technologies this specific project uses that make it more impressive than a surface read would
  suggest (e.g. mentioning "hybrid retrieval with FAISS and BM25" instead of just "a chatbot")
- Is framed toward the target role(s) given — emphasize the angle relevant to that role without
  fabricating relevance that isn't there

Always respond with valid JSON only, no markdown fences, no commentary."""

PROJECT_DESC_USER_PROMPT_TEMPLATE = """Target role(s): {roles}

Projects (JSON array — each project's ONLY allowed source material is its own fields below):
{projects_json}

Return a JSON object with this exact shape:
{{
  "descriptions": [
    {{"name": "<project name>", "blurb": "<2-4 sentence description>", "highlighted_tech": ["<tech names actually used in the blurb>"]}}
  ]
}}
Include every project from the input."""


def generate_project_descriptions(
    client: LLMClient, roles: list, repo_briefs: list
) -> list:
    prompt = PROJECT_DESC_USER_PROMPT_TEMPLATE.format(
        roles=", ".join(roles),
        projects_json=json.dumps(repo_briefs, indent=2),
    )
    result = client.chat_json(
        PROJECT_DESC_SYSTEM_PROMPT, prompt, temperature=0.4, max_tokens=4096
    )
    return result.get("descriptions", [])


# ---------- bio (one LLM call) ----------

BIO_SYSTEM_PROMPT = """You are an expert technical resume/portfolio writer.

CRITICAL GROUNDING RULE: only reference facts explicitly present in the data you're given —
existing bio text, work experience (company, title, description), education, certifications,
awards, publications, additional named skills, project names, and aggregated technology names.
NEVER invent employers, job titles, dates, degrees, certifications, awards, years of experience,
metrics, or achievements not stated in the provided data. If work experience has no duration
given, don't guess one or state a number of years — omit timeframes entirely rather than
fabricate them.

Write a 3-5 sentence professional bio that:
- Opens with who they are professionally, framed toward the target role(s)
- Weaves in real work experience (company/title, and what they actually did, if provided)
- Mentions certifications, education, or awards ONLY if they're genuinely relevant and provided —
  don't force them in if they don't add to the narrative
- References the genuine breadth of technology shown by their project portfolio (use the
  aggregated technology list given, don't invent items not in it)
- Sounds like a confident, natural bio a person would put on their own portfolio — not a
  resume bullet list, not third-person corporate-speak

Always respond with valid JSON only, no markdown fences, no commentary."""

BIO_USER_PROMPT_TEMPLATE = """Target role(s): {roles}

Existing self-written bio (may be empty): {existing_bio}

Work experience (JSON array, may be empty):
{work_experience_json}

Certifications (JSON array, may be empty):
{certifications_json}

Education (JSON array, may be empty):
{education_json}

Awards (JSON array, may be empty):
{awards_json}

Publications (JSON array, may be empty):
{publications_json}

Additional named skills (may be empty): {additional_skills}

Technologies demonstrated across featured projects and work experience (aggregated, deduped):
{aggregated_tech_json}

Featured project names (for context on breadth, don't need to name every one): {project_names}

Return a JSON object with this exact shape:
{{
  "bio": "<3-5 sentence bio>",
  "suggested_title": "<a short professional title/tagline, e.g. 'Backend Engineer & AI Systems Builder'>"
}}"""


def generate_bio(
    client: LLMClient,
    roles: list,
    profile_bio: Optional[str],
    work_experience: list,
    aggregated_tech: list,
    project_names: list,
    certifications: Optional[list] = None,
    education: Optional[list] = None,
    awards: Optional[list] = None,
    publications: Optional[list] = None,
    additional_skills: Optional[list] = None,
) -> dict:
    prompt = BIO_USER_PROMPT_TEMPLATE.format(
        roles=", ".join(roles),
        existing_bio=profile_bio or "(none provided)",
        work_experience_json=json.dumps(work_experience, indent=2),
        certifications_json=json.dumps(certifications or [], indent=2),
        education_json=json.dumps(education or [], indent=2),
        awards_json=json.dumps(awards or [], indent=2),
        publications_json=json.dumps(publications or [], indent=2),
        additional_skills=", ".join(additional_skills or []) or "(none)",
        aggregated_tech_json=json.dumps(aggregated_tech, indent=2),
        project_names=", ".join(project_names),
    )
    return client.chat_json(BIO_SYSTEM_PROMPT, prompt, temperature=0.4, max_tokens=1024)


# ---------- skills summary (deterministic — no LLM, no room for fabrication) ----------


def build_skills_summary(repo_scans: list, work_experience_stack: list) -> dict:
    """
    Pure aggregation of what Phase 3 already found — deliberately NOT an LLM
    call. There's no judgment required here (it's just "what real, distinctive
    tech showed up across everything"), so keeping it deterministic removes
    any chance of the summary drifting from the actual evidence.

    Always includes a "Languages" category aggregated from each repo's
    GitHub-reported languages, independent of whether any dependency-manifest
    tech was detected. This matters a lot for portfolios outside the
    Python/AI world Phase 3's TECH_DICTIONARY was originally built around —
    a person whose repos are plain HTML/CSS/JS or Android/Java projects with
    no recognized package-manager tech would otherwise get a completely
    empty skills section, which undersells them for no good reason. GitHub
    always reports languages, so this is a reliable floor for anyone with
    real repo activity.
    """
    by_category = {}

    def add(name, category):
        by_category.setdefault(category, set()).add(name)

    for scan in repo_scans:
        for tech in scan.get("detected_stack", []):
            if not tech.get("environment_wide"):
                add(tech["name"], tech["category"])
        for lang in scan.get("languages", []):
            add(lang, "Languages")

    for job in work_experience_stack:
        for tech in job.get("detected_stack", []):
            add(tech["name"], tech["category"])

    return {category: sorted(names) for category, names in sorted(by_category.items())}


# ---------- orchestration ----------


def run_phase4(
    phase1_path: str,
    phase2_path: str,
    phase3_path: str,
    output_path: str = "phase4_output.json",
) -> dict:
    with open(phase1_path, "r", encoding="utf-8") as f:
        phase1_data = json.load(f)
    with open(phase2_path, "r", encoding="utf-8") as f:
        phase2_data = json.load(f)
    with open(phase3_path, "r", encoding="utf-8") as f:
        phase3_data = json.load(f)

    roles = phase2_data["roles"]
    featured_names = phase2_data["featured_repo_names"]
    work_experience = phase2_data.get("work_experience") or []
    certifications = phase2_data.get("certifications") or []
    education = phase2_data.get("education") or []
    awards = phase2_data.get("awards") or []
    publications = phase2_data.get("publications") or []
    additional_skills = phase2_data.get("additional_skills") or []

    repos_by_name = {r["name"]: r for r in phase1_data["repos"]}
    tech_scans_by_name = {r["name"]: r for r in phase3_data["repos"]}
    work_experience_stack = phase3_data.get("work_experience_stack") or []

    client = LLMClient()

    print("Generating project descriptions...")
    repo_briefs = [
        build_repo_content_brief(repos_by_name[name], tech_scans_by_name.get(name))
        for name in featured_names
        if name in repos_by_name
    ]
    descriptions = generate_project_descriptions(client, roles, repo_briefs)
    for d in descriptions:
        print(f"  {d['name']}: {d['blurb'][:80]}...")

    print("\nGenerating bio...")
    aggregated_skills = build_skills_summary(
        [
            tech_scans_by_name[name]
            for name in featured_names
            if name in tech_scans_by_name
        ],
        work_experience_stack,
    )
    aggregated_tech_flat = sorted(
        {name for names in aggregated_skills.values() for name in names}
    )
    profile_bio = phase1_data.get("profile", {}).get("bio")

    bio_result = generate_bio(
        client,
        roles,
        profile_bio,
        work_experience,
        aggregated_tech_flat,
        featured_names,
        certifications=certifications,
        education=education,
        awards=awards,
        publications=publications,
        additional_skills=additional_skills,
    )
    print(f"  Bio: {bio_result.get('bio', '')[:100]}...")
    print(f"  Title: {bio_result.get('suggested_title', '')}")

    output = {
        "roles": roles,
        "bio": bio_result.get("bio", ""),
        "suggested_title": bio_result.get("suggested_title", ""),
        "project_descriptions": descriptions,
        "skills_summary": aggregated_skills,
        # Pass-through, not LLM-generated — these are already human-confirmed
        # facts from Phase 2, so Phase 5 renders them directly with no
        # additional risk of drift from what was actually provided.
        "certifications": certifications,
        "education": education,
        "awards": awards,
        "publications": publications,
        "additional_skills": additional_skills,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"\nSaved Phase 4 output to {output_path}")
    return output


if __name__ == "__main__":
    phase1_path = (
        sys.argv[1]
        if len(sys.argv) > 1
        else input("Path to Phase 1 JSON file: ").strip()
    )
    phase2_path = (
        sys.argv[2]
        if len(sys.argv) > 2
        else input("Path to Phase 2 JSON file: ").strip()
    )
    phase3_path = (
        sys.argv[3]
        if len(sys.argv) > 3
        else input("Path to Phase 3 JSON file: ").strip()
    )
    try:
        run_phase4(phase1_path, phase2_path, phase3_path)
    except LLMError as e:
        print(f"\nLLM error: {e}")
        sys.exit(1)
