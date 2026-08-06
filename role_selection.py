"""
Phase 2: Role input + AI-ranked repo selection + skills-gap analysis.

Flow (human-in-the-loop at every AI decision point):
  1. Ask the user for 1-3 target roles.
  2. AI ranks ALL repos (from the Phase 1 JSON) by relevance to those roles.
  3. User reviews the ranked list and picks which repos to actually include
     (AI's top picks are shown as the default, user can override).
  4. AI compares the selected repos against what's typically expected for
     the target role(s) and produces a gap report.
  5. For each gap, AI RE-SCANS THE FULL REPO SET (not just the unselected
     ones — see design note below) to see if an existing repo could fill it.
  6. User confirms or rejects each suggested addition. Nothing is added
     silently.

Design note on "full rescan": we deliberately re-examine every repo, not
just the ones the user didn't pick, when checking for gap fits. A repo the
user already selected might genuinely fill a gap that its initial one-line
framing didn't surface — re-checking everything is strictly more accurate,
and since this is all just local JSON (no new GitHub API calls), there's no
real cost to being thorough.
"""

import json
import re
import sys
from typing import Optional

from llm_client import LLMClient, LLMError

README_EXCERPT_LEN = (
    300  # kept short deliberately — with 20-30 repos in one prompt, full
)
# READMEs would blow through free-tier per-minute token limits fast


def load_profile_data(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def ask_target_roles() -> list:
    print("\nWhat role(s) are you targeting? (up to 3, comma-separated)")
    print("e.g. Backend Engineer, ML Engineer")
    raw = input("> ").strip()
    roles = [r.strip() for r in raw.split(",") if r.strip()]
    if not roles:
        print("No roles entered. Exiting.")
        sys.exit(1)
    return roles[:3]


def build_repo_brief(repo: dict) -> dict:
    """Compact representation of a repo for LLM prompts — keeps token usage low.
    Deliberately excludes stars/forks/is_archived: the ranking prompt already
    instructs the model to ignore those, so including them just burns tokens
    for no benefit (matters a lot on free-tier per-minute limits)."""
    readme = repo.get("readme_text") or ""
    return {
        "name": repo["name"],
        "description": repo.get("description") or "",
        "readme_excerpt": readme[:README_EXCERPT_LEN],
        "languages": list((repo.get("languages") or {}).keys()),
        "topics": repo.get("topics") or [],
    }


# ---------- Step 2: AI-ranked repo selection ----------

RANKING_SYSTEM_PROMPT = """You are an expert technical recruiter and portfolio advisor.
You rank a developer's GitHub repos by how relevant each one is to a set of target job roles.
Score based on: relevance of the tech stack/topic to the role, apparent depth (README quality,
described complexity), and recency signals. Ignore stars/forks — they don't matter for a personal
portfolio. Demo/tutorial-following repos with no real content should score low.
Always respond with valid JSON only, no markdown fences, no commentary."""

RANKING_USER_PROMPT_TEMPLATE = """Target role(s): {roles}

Repos (JSON array):
{repos_json}

Return a JSON object with this exact shape:
{{
  "rankings": [
    {{"name": "<repo name>", "relevance_score": <0-100 int>, "reason": "<one sentence>"}}
  ]
}}
Include EVERY repo from the input, sorted by relevance_score descending."""


def rank_repos_for_roles(client: LLMClient, roles: list, repo_briefs: list) -> list:
    prompt = RANKING_USER_PROMPT_TEMPLATE.format(
        roles=", ".join(roles),
        repos_json=json.dumps(repo_briefs, indent=2),
    )
    result = client.chat_json(RANKING_SYSTEM_PROMPT, prompt, temperature=0.2)
    rankings = result.get("rankings", [])
    rankings.sort(key=lambda r: r.get("relevance_score", 0), reverse=True)
    return rankings


def present_rankings_and_select(rankings: list, all_repo_names: set) -> list:
    print("\n" + "=" * 70)
    print("AI-suggested repo ranking for your target role(s):")
    print("=" * 70)
    for i, r in enumerate(rankings, 1):
        print(f"  {i:2d}. [{r.get('relevance_score', 0):3d}] {r['name']}")
        print(f"        {r.get('reason', '')}")

    # Default suggestion: anything scoring 60+
    suggested_indices = [
        i for i, r in enumerate(rankings, 1) if r.get("relevance_score", 0) >= 60
    ]
    suggested_str = ",".join(str(i) for i in suggested_indices)

    print(f"\nSuggested selection (score >= 60): {suggested_str or '(none)'}")
    print("Press Enter to accept the suggestion, or type your own comma-separated")
    print("numbers (e.g. 1,2,4) to override:")
    raw = input("> ").strip()

    if not raw:
        chosen_indices = suggested_indices
    else:
        try:
            chosen_indices = [int(x.strip()) for x in raw.split(",") if x.strip()]
        except ValueError:
            print("Couldn't parse that input, falling back to the AI suggestion.")
            chosen_indices = suggested_indices

    selected_names = []
    for i in chosen_indices:
        if 1 <= i <= len(rankings):
            selected_names.append(rankings[i - 1]["name"])

    return selected_names


# ---------- Step 4-5: gap analysis with full rescan ----------

GAP_SYSTEM_PROMPT = """You are an expert technical recruiter advising a candidate on portfolio gaps.
Given a set of target roles and the repos a candidate has selected to feature, identify what's
typically expected for those roles that seems to be MISSING from the selection (e.g. no testing/CI,
no deployment/live demo, no data-heavy project, no collaborative/team-sized project, etc).
Be specific and only flag genuine, meaningful gaps — do not pad the list. 2-4 gaps is typical; if the
selection is genuinely strong, say so with an empty gaps list.
Always respond with valid JSON only, no markdown fences, no commentary."""

GAP_USER_PROMPT_TEMPLATE = """Target role(s): {roles}

Selected repos (JSON array):
{selected_json}

Return a JSON object with this exact shape:
{{
  "gaps": [
    {{"gap": "<short label, e.g. 'No deployment/live demo'>", "why_it_matters": "<one sentence>"}}
  ]
}}"""


def find_literal_keyword_matches(gap_label: str, all_repo_briefs: list) -> list:
    """
    Deterministic pre-check, independent of the LLM: for common gap categories
    (collaboration, testing, deployment, documentation), search each repo's
    description and readme_excerpt for known synonym keywords — not just words
    literally present in the gap label itself.

    This exists because a single LLM call scanning 20-30 repos at once can miss an
    explicit match purely due to attention dilution across a long list, AND because
    naive literal-word matching on the gap label alone misses synonyms (a gap labeled
    "team-sized project" won't literally contain the word a repo actually uses, e.g.
    description="Group project" — "team" and "group" are synonyms, not the same string).
    Results are passed to the LLM as hints, not auto-added — the LLM still makes
    (and the user still confirms) the final call.
    """
    CATEGORY_SYNONYMS = [
        {
            "triggers": ["collaborat", "team"],
            "keywords": [
                "team",
                "teams",
                "collab",
                "group project",
                "group work",
                "pair program",
                "hackathon",
                "co-founder",
                "contributors",
            ],
        },
        {
            "triggers": ["test", " ci", "ci/cd", "continuous integration"],
            "keywords": [
                "test",
                "tests",
                "testing",
                "pytest",
                "unittest",
                "ci/cd",
                "continuous integration",
                "github actions",
                "coverage",
            ],
        },
        {
            "triggers": ["deploy", "live demo", "live "],
            "keywords": [
                "deploy",
                "deployed",
                "live demo",
                "hosted",
                "vercel",
                "heroku",
                "streamlit cloud",
                "github pages",
                "render.com",
                "railway",
                "production",
                "www.",
                "http://",
                "https://",
            ],
        },
        {"triggers": ["document"], "keywords": ["documentation", "docs", "wiki"]},
    ]

    gap_lower = gap_label.lower()
    search_terms = set()

    for category in CATEGORY_SYNONYMS:
        if any(trigger in gap_lower for trigger in category["triggers"]):
            search_terms.update(category["keywords"])

    # Fallback: also include raw significant words straight from the gap label,
    # so gap types outside the taxonomy above still get some deterministic coverage.
    STOPWORDS = {
        "no",
        "a",
        "an",
        "the",
        "of",
        "or",
        "and",
        "project",
        "sized",
        "focused",
    }
    words = re.findall(r"[a-zA-Z]+", gap_lower)
    search_terms.update(w for w in words if w not in STOPWORDS and len(w) > 3)

    matches = []
    for brief in all_repo_briefs:
        haystack = (
            f"{brief.get('description', '')} {brief.get('readme_excerpt', '')}".lower()
        )
        hit_terms = [term for term in search_terms if term in haystack]
        if hit_terms:
            matches.append({"name": brief["name"], "matched_keywords": hit_terms})
    return matches


RESCAN_SYSTEM_PROMPT = """You are an expert technical recruiter. You are given a specific portfolio
gap and the candidate's FULL list of GitHub repos (including ones they didn't originally select).

Check whether ANY repo in the full list could plausibly fill that gap, even partially.

IMPORTANT — with a large repo list, it's easy to skim past a direct match. Before concluding
nothing fits, explicitly scan each repo's "description" field first (it's short and often
contains the clearest literal signal, e.g. a description mentioning "group project", "team",
"deployed", "live", "tested", "CI/CD" is direct evidence for gaps like collaboration,
deployment, or testing) — only fall back to the readme_excerpt and topics if description is
empty or unhelpful. Be honest: if nothing fits after that check, say so. Do not force a weak
match, but do not miss an explicit, literal match either.

Always respond with valid JSON only, no markdown fences, no commentary."""

RESCAN_USER_PROMPT_TEMPLATE = """Gap to fill: {gap}
Why it matters: {why}

Deterministic keyword pre-check found these possible literal matches (repo name -> matched
words from the gap label found in its description/readme) — treat these as strong candidates
to verify first, but don't treat this list as exhaustive or authoritative on its own:
{keyword_hints}

Full repo list (JSON array, includes both selected and unselected repos):
{all_repos_json}

First, mentally check each repo's "description" field for a direct literal match to this gap.
Then return a JSON object with this exact shape:
{{
  "fit_found": <true/false>,
  "repo_name": "<name if fit_found is true, else null>",
  "explanation": "<why this repo fits the gap, or why nothing in the list fits>"
}}"""


def analyze_gaps(client: LLMClient, roles: list, selected_briefs: list) -> list:
    prompt = GAP_USER_PROMPT_TEMPLATE.format(
        roles=", ".join(roles),
        selected_json=json.dumps(selected_briefs, indent=2),
    )
    result = client.chat_json(GAP_SYSTEM_PROMPT, prompt, temperature=0.3)
    return result.get("gaps", [])


def rescan_for_gap_fit(client: LLMClient, gap: dict, all_repo_briefs: list) -> dict:
    keyword_matches = find_literal_keyword_matches(gap["gap"], all_repo_briefs)
    hints_str = json.dumps(keyword_matches) if keyword_matches else "(none found)"

    prompt = RESCAN_USER_PROMPT_TEMPLATE.format(
        gap=gap["gap"],
        why=gap.get("why_it_matters", ""),
        keyword_hints=hints_str,
        all_repos_json=json.dumps(all_repo_briefs, indent=2),
    )
    return client.chat_json(RESCAN_SYSTEM_PROMPT, prompt, temperature=0.0)


def run_gap_analysis_with_confirmation(
    client: LLMClient, roles: list, selected_names: list, all_repo_briefs: list
) -> tuple:
    """
    Returns (final_selected_names, gap_added_names, unresolved_gaps).
    gap_added_names tracks which repos were added specifically because they filled
    an identified gap — Phase 5's top-10 cutoff gives these guaranteed priority,
    since dropping them for raw relevance score would undo the whole point of
    running this gap check in the first place.
    unresolved_gaps tracks gaps where no repo filled it — these get checked against
    work experience next, since a real job often resolves things GitHub can't show
    (e.g. "no collaborative project").
    """
    selected_briefs = [b for b in all_repo_briefs if b["name"] in selected_names]
    gap_added_names = []
    unresolved_gaps = []

    print("\n" + "=" * 70)
    print("Checking your selection against what's typical for these role(s)...")
    print("=" * 70)

    gaps = analyze_gaps(client, roles, selected_briefs)

    if not gaps:
        print("No significant gaps found — your selection looks solid for these roles.")
        return selected_names, gap_added_names, unresolved_gaps

    for gap in gaps:
        print(f"\nGap: {gap['gap']}")
        print(f"  Why it matters: {gap.get('why_it_matters', '')}")
        print("  Re-scanning your full repo list for a possible fit...")

        fit = rescan_for_gap_fit(client, gap, all_repo_briefs)

        if not fit.get("fit_found"):
            print(f"  No existing repo fills this gap. ({fit.get('explanation', '')})")
            print("  Consider building something here if this role matters to you.")
            unresolved_gaps.append(gap)
            continue

        candidate = fit.get("repo_name")
        print(f"  Possible fit found: '{candidate}'")
        print(f"  Reasoning: {fit.get('explanation', '')}")

        if candidate in selected_names:
            print(f"  ('{candidate}' is already in your selection.)")
            continue

        answer = (
            input(f"  Add '{candidate}' to your selection? (y/n): ").strip().lower()
        )
        if answer == "y":
            selected_names.append(candidate)
            gap_added_names.append(candidate)
            print(f"  Added '{candidate}'.")
        else:
            print("  Skipped.")

    return selected_names, gap_added_names, unresolved_gaps


def compute_featured_repos(
    selected_names: list, gap_added_names: list, rankings: list, max_featured: int = 10
) -> list:
    """
    Hard-caps the portfolio display list at max_featured repos. Gap-fill additions
    get guaranteed priority (they were added to fix a specific identified weakness —
    cutting them for raw relevance score would undo that work). Remaining slots go
    to the highest-scored repos from the original ranking.
    """
    score_by_name = {r["name"]: r.get("relevance_score", 0) for r in rankings}

    # Gap-fill repos first, guaranteed inclusion (unless there are somehow more than
    # max_featured of them, in which case keep the ones found earliest).
    featured = list(gap_added_names[:max_featured])

    remaining_slots = max_featured - len(featured)
    if remaining_slots > 0:
        others = [n for n in selected_names if n not in featured]
        others.sort(key=lambda n: score_by_name.get(n, 0), reverse=True)
        featured.extend(others[:remaining_slots])

    return featured


# ---------- Step 6 (new): work experience not reflected on GitHub ----------


def ask_work_experience() -> list:
    """
    GitHub only shows public/open-source work — a person's strongest, most
    relevant experience is often a job that never touched a public repo.
    This collects that experience directly from the user rather than having
    AI invent it, mirroring the anti-hallucination guardrail pattern from
    ai-resume-cover-letter: ask for what they actually did, use any pasted
    job description only as supporting context/keywords, never as a source
    of fabricated achievements.
    """
    print("\n" + "=" * 70)
    print("Work experience (optional)")
    print("=" * 70)
    print("GitHub only shows public projects — if you have relevant work experience")
    print(
        "that isn't reflected there, you can add it here to strengthen your portfolio."
    )

    answer = input("Do you want to add any work experience? (y/n): ").strip().lower()
    if answer != "y":
        return []

    jobs = []
    while True:
        print(f"\n--- Job #{len(jobs) + 1} ---")
        company = input("Company name: ").strip()
        title = input("Job title: ").strip()
        duration = input("Duration (e.g. 'Jan 2023 - Present'): ").strip()

        print("Briefly describe what YOU actually did in this role")
        print("(your own words — this is what gets used, not the job description):")
        description = input("> ").strip()

        print("Optional: paste the job description for extra context/keywords")
        print("(press Enter to skip):")
        jd = input("> ").strip()

        jobs.append(
            {
                "company": company,
                "title": title,
                "duration": duration,
                "description": description,
                "job_description": jd or None,
            }
        )

        more = input("\nAdd another job? (y/n): ").strip().lower()
        if more != "y":
            break

    return jobs


WORK_EXPERIENCE_GAP_CHECK_SYSTEM_PROMPT = """You are an expert technical recruiter. You are given a
list of previously-identified portfolio gaps (things missing from a candidate's GitHub-based
selection) and the candidate's work experience (not on GitHub). Check whether any of these gaps
are actually already addressed by their work experience — e.g. a "no collaborative project" gap
is likely satisfied by any real job, since jobs are inherently collaborative.
Always respond with valid JSON only, no markdown fences, no commentary."""

WORK_EXPERIENCE_GAP_CHECK_USER_PROMPT_TEMPLATE = """Previously unresolved gaps:
{gaps_json}

Work experience:
{jobs_json}

Return a JSON object with this exact shape:
{{
  "resolved_gaps": [
    {{"gap": "<gap label>", "resolved_by": "<which job>", "explanation": "<one sentence>"}}
  ]
}}
Only include gaps that are genuinely addressed — do not force a match."""


def check_work_experience_against_gaps(
    client: LLMClient, unresolved_gaps: list, jobs: list
) -> list:
    if not unresolved_gaps or not jobs:
        return []
    prompt = WORK_EXPERIENCE_GAP_CHECK_USER_PROMPT_TEMPLATE.format(
        gaps_json=json.dumps(unresolved_gaps, indent=2),
        jobs_json=json.dumps(jobs, indent=2),
    )
    result = client.chat_json(
        WORK_EXPERIENCE_GAP_CHECK_SYSTEM_PROMPT, prompt, temperature=0.0
    )
    return result.get("resolved_gaps", [])


# ---------- orchestration ----------


def run_phase2(profile_json_path: str, output_path: str = "phase2_output.json"):
    data = load_profile_data(profile_json_path)
    repos = data["repos"]
    repo_briefs = [build_repo_brief(r) for r in repos]
    all_repo_names = {r["name"] for r in repos}

    client = LLMClient()  # reads GROQ_API_KEY from .env

    roles = ask_target_roles()
    print(f"\nTarget role(s): {', '.join(roles)}")

    print("\nRanking your repos against these role(s)...")
    rankings = rank_repos_for_roles(client, roles, repo_briefs)

    selected_names = present_rankings_and_select(rankings, all_repo_names)
    print(
        f"\nSelected repos: {', '.join(selected_names) if selected_names else '(none)'}"
    )

    selected_names, gap_added_names, unresolved_gaps = (
        run_gap_analysis_with_confirmation(client, roles, selected_names, repo_briefs)
    )

    featured_repo_names = compute_featured_repos(
        selected_names, gap_added_names, rankings, max_featured=10
    )

    work_experience = ask_work_experience()

    resolved_by_experience = []
    if work_experience and unresolved_gaps:
        print("\nChecking whether your work experience addresses the remaining gaps...")
        resolved_by_experience = check_work_experience_against_gaps(
            client, unresolved_gaps, work_experience
        )
        for r in resolved_by_experience:
            print(
                f"  '{r['gap']}' is addressed by your experience at {r['resolved_by']}: {r['explanation']}"
            )

    result = {
        "roles": roles,
        "selected_repo_names": selected_names,  # full working set — everything the user approved
        "featured_repo_names": featured_repo_names,  # hard-capped top 10 for the actual portfolio page
        "gap_added_names": gap_added_names,
        "unresolved_gaps": unresolved_gaps,
        "work_experience": work_experience,
        "gaps_resolved_by_experience": resolved_by_experience,
        "all_repo_names": list(all_repo_names),
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(f"\nSaved Phase 2 output to {output_path}")
    print(f"Full selection ({len(selected_names)}): {', '.join(selected_names)}")
    print(
        f"Featured for portfolio ({len(featured_repo_names)}): {', '.join(featured_repo_names)}"
    )
    if len(selected_names) > len(featured_repo_names):
        dropped = [n for n in selected_names if n not in featured_repo_names]
        print(
            f"Not featured (still in your full selection, just not top 10): {', '.join(dropped)}"
        )
    if work_experience:
        print(f"Work experience entries: {len(work_experience)}")
    return result


if __name__ == "__main__":
    profile_path = (
        sys.argv[1]
        if len(sys.argv) > 1
        else input("Path to Phase 1 JSON file: ").strip()
    )
    try:
        run_phase2(profile_path)
    except LLMError as e:
        print(f"\nLLM error: {e}")
        sys.exit(1)
    except FileNotFoundError:
        print(f"\nFile not found: {profile_path}")
        sys.exit(1)
