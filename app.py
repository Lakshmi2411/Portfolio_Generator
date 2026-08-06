"""
Phase 6: Streamlit app.

Wraps Phase 1-5 in a real UI. The orchestrator (orchestrator.py) already
eliminated file-path prompting between phases — this app replaces Phase 2's
terminal input() prompts (which can't work in Streamlit's rerun-on-interaction
model) with actual widgets, while Phase 1, 3, 4, 5 run automatically since
they need no human judgment.

Flow (session_state["step"] drives which screen shows):
  fetch    -> username + token, runs Phase 1
  roles    -> enter target roles, AI ranks repos
  select   -> checkboxes to confirm/override the AI's suggested selection
  gaps     -> one gap at a time, AI proposes a fit, user clicks Add/Skip
  workexp  -> add work experience not on GitHub (optional, repeatable form)
  generate -> runs Phase 3+4+5 automatically (no human input needed here)
  done     -> preview the rendered portfolio + download button
"""

import json
import os

import streamlit as st

from github_fetcher import GitHubFetcher, save_profile_json, GitHubAPIError
from llm_client import LLMClient, LLMError
from role_selection import (
    build_repo_brief, rank_repos_for_roles, analyze_gaps, rescan_for_gap_fit,
    compute_featured_repos, check_work_experience_against_gaps,
)
from technical_scan import run_phase3
from content_generation import run_phase4
from portfolio_template import run_phase5


st.set_page_config(page_title="Portfolio Generator", page_icon="\U0001F6E0\uFE0F", layout="centered")


def init_state():
    defaults = {
        "step": "fetch",
        "username": "",
        "phase1_data": None,
        "phase1_path": None,
        "roles": [],
        "repo_briefs": [],
        "rankings": [],
        "selected_names": [],
        "gaps": [],
        "gap_index": 0,
        "gap_added_names": [],
        "unresolved_gaps": [],
        "current_gap_fit": None,
        "work_experience": [],
        "certifications": [],
        "education": [],
        "awards": [],
        "publications": [],
        "additional_skills": [],
        "num_job_forms": 1,
        "preferred_name": "",
        "resume_name": "",
        "portfolio_path": None,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


init_state()
paths_dir = "portfolio_output"
os.makedirs(paths_dir, exist_ok=True)


def go_to(step):
    st.session_state.step = step
    st.rerun()


st.title("\U0001F6E0\uFE0F GitHub Portfolio Generator")

# ---------------------------------------------------------------- fetch ----
if st.session_state.step == "fetch":
    st.write("Turn your GitHub projects into a role-targeted portfolio.")
    username = st.text_input("GitHub username", value=st.session_state.username)

    with st.expander("Advanced (optional)"):
        max_repos = st.number_input("Max repos to fetch (blank = all public repos)",
                                     min_value=0, value=0, step=1)

    if st.button("Fetch my GitHub", type="primary", disabled=not username):
        st.session_state.username = username
        try:
            with st.spinner("Fetching your repos, languages, READMEs, and dependency files..."):
                fetcher = GitHubFetcher()
                mr = int(max_repos) if max_repos else None
                if mr is None:
                    profile = fetcher.get_user_profile(username)
                    mr = max(profile.public_repos, 1)
                result = fetcher.fetch_full_profile(username, max_repos=mr)
                phase1_path = os.path.join(paths_dir, f"{username}_phase1_github.json")
                save_profile_json(result, phase1_path)
            st.session_state.phase1_data = result
            st.session_state.phase1_path = phase1_path
            st.success(f"Fetched {len(result['repos'])} repos for {result['profile'].get('name') or username}.")
            go_to("roles")
        except GitHubAPIError as e:
            st.error(f"GitHub API error: {e}")

# ---------------------------------------------------------------- roles ----
elif st.session_state.step == "roles":
    profile = st.session_state.phase1_data["profile"]
    default_name = profile.get("name") or profile.get("username") or "your name"
    preferred_name = st.text_input("Name to show on your portfolio", placeholder=default_name,
                                    help="Leave blank to auto-detect from GitHub or an uploaded resume.")
    st.session_state.preferred_name = preferred_name

    st.subheader("Target role(s)")
    st.write("Up to 3 roles. Your repos will be ranked and framed around these.")

    roles_input = st.text_input("Roles (comma-separated)", placeholder="Backend Engineer, Data Analyst")

    if st.button("Rank my repos", type="primary", disabled=not roles_input.strip()):
        roles = [r.strip() for r in roles_input.split(",") if r.strip()][:3]
        st.session_state.roles = roles
        repos = st.session_state.phase1_data["repos"]
        repo_briefs = [build_repo_brief(r) for r in repos]
        st.session_state.repo_briefs = repo_briefs

        try:
            with st.spinner(f"Ranking {len(repo_briefs)} repos against {', '.join(roles)}..."):
                client = LLMClient()
                rankings = rank_repos_for_roles(client, roles, repo_briefs)
            st.session_state.rankings = rankings
            go_to("select")
        except LLMError as e:
            st.error(f"LLM error: {e}")

# --------------------------------------------------------------- select ----
elif st.session_state.step == "select":
    st.subheader("Confirm your repo selection")
    st.write("AI-suggested picks are pre-checked (score \u2265 60). Adjust as you like.")

    rankings = st.session_state.rankings
    checked_names = []
    for r in rankings:
        default_checked = r.get("relevance_score", 0) >= 60
        label = f"**[{r.get('relevance_score', 0)}]** {r['name']} \u2014 {r.get('reason', '')}"
        checked = st.checkbox(label, value=default_checked, key=f"select_{r['name']}")
        if checked:
            checked_names.append(r["name"])

    if st.button("Confirm selection", type="primary", disabled=not checked_names):
        st.session_state.selected_names = checked_names
        st.session_state.gap_index = 0
        st.session_state.gaps = []
        go_to("gaps")

# ---------------------------------------------------------------- gaps -----
elif st.session_state.step == "gaps":
    st.subheader("Gap check")

    # Run the gap analysis once, first time we land on this screen.
    if not st.session_state.gaps and st.session_state.gap_index == 0 and "gaps_checked" not in st.session_state:
        selected_briefs = [b for b in st.session_state.repo_briefs if b["name"] in st.session_state.selected_names]
        try:
            with st.spinner("Checking your selection against what's typical for these roles..."):
                client = LLMClient()
                gaps = analyze_gaps(client, st.session_state.roles, selected_briefs)
            st.session_state.gaps = gaps
            st.session_state.gaps_checked = True
        except LLMError as e:
            st.error(f"LLM error: {e}")
            st.stop()

    gaps = st.session_state.gaps
    idx = st.session_state.gap_index

    if not gaps:
        st.success("No significant gaps found \u2014 your selection looks solid.")
        if st.button("Continue", type="primary"):
            go_to("workexp")

    elif idx >= len(gaps):
        st.success("Gap check complete.")
        if st.button("Continue", type="primary"):
            st.session_state.unresolved_gaps = [
                g for g in gaps if g["gap"] not in
                {a["gap"] for a in st.session_state.get("resolved_gap_labels", [])}
            ]
            go_to("workexp")

    else:
        gap = gaps[idx]
        st.write(f"**Gap {idx + 1}/{len(gaps)}: {gap['gap']}**")
        st.caption(gap.get("why_it_matters", ""))

        if st.session_state.current_gap_fit is None:
            try:
                with st.spinner("Re-scanning your full repo list for a possible fit..."):
                    client = LLMClient()
                    fit = rescan_for_gap_fit(client, gap, st.session_state.repo_briefs)
                st.session_state.current_gap_fit = fit
            except LLMError as e:
                st.error(f"LLM error: {e}")
                st.stop()

        fit = st.session_state.current_gap_fit

        def advance(unresolved=False):
            if unresolved:
                st.session_state.unresolved_gaps.append(gap)
            st.session_state.current_gap_fit = None
            st.session_state.gap_index += 1
            st.rerun()

        if not fit.get("fit_found"):
            st.info(f"No existing repo fills this gap. {fit.get('explanation', '')}")
            if st.button("Next", key=f"next_{idx}"):
                advance(unresolved=True)
        else:
            candidate = fit.get("repo_name")
            already_in = candidate in st.session_state.selected_names
            if already_in:
                st.info(f"'{candidate}' already covers this: {fit.get('explanation', '')}")
                if st.button("Next", key=f"next_{idx}"):
                    advance()
            else:
                st.write(f"Possible fit: **{candidate}**")
                st.caption(fit.get("explanation", ""))
                col1, col2 = st.columns(2)
                if col1.button(f"Add '{candidate}'", type="primary", key=f"add_{idx}"):
                    st.session_state.selected_names.append(candidate)
                    st.session_state.gap_added_names.append(candidate)
                    advance()
                if col2.button("Skip", key=f"skip_{idx}"):
                    advance(unresolved=True)

# -------------------------------------------------------------- workexp ----
elif st.session_state.step == "workexp":
    st.subheader("Work experience & credentials (optional)")
    st.write("GitHub only shows public projects. Add jobs, certifications, education, awards, "
             "publications, or other skills not reflected there to strengthen your portfolio.")
    st.caption("Describe what YOU actually did, in your own words \u2014 that's what gets used, "
               "not a pasted job description.")

    with st.expander("Upload a resume to auto-fill (optional)", expanded=False):
        resume_file = st.file_uploader("Resume file", type=["pdf", "docx", "txt"])
        if st.button("Extract from resume", disabled=resume_file is None):
            import tempfile
            from resume_parser import parse_resume_file, ResumeParseError

            suffix = os.path.splitext(resume_file.name)[1]
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(resume_file.getvalue())
                tmp_path = tmp.name

            try:
                with st.spinner("Extracting and parsing your resume..."):
                    client = LLMClient()
                    extracted = parse_resume_file(client, tmp_path)
            except (ResumeParseError, LLMError) as e:
                st.error(f"Couldn't parse that resume: {e}")
                extracted = {"name": "", "jobs": [], "certifications": [], "education": [],
                             "awards": [], "publications": [], "additional_skills": []}
            finally:
                os.unlink(tmp_path)

            total_found = sum(len(extracted[k]) for k in extracted if k != "name")
            if extracted.get("name"):
                st.session_state.resume_name = extracted["name"]
            if total_found:
                jobs_found = extracted["jobs"]
                if jobs_found:
                    st.session_state.num_job_forms = max(st.session_state.num_job_forms, len(jobs_found))
                    for i, job in enumerate(jobs_found):
                        st.session_state[f"company_{i}"] = job["company"]
                        st.session_state[f"title_{i}"] = job["title"]
                        st.session_state[f"duration_{i}"] = job["duration"]
                        st.session_state[f"desc_{i}"] = job["description"]

                # Certifications/education/awards/publications/skills go straight
                # to session_state as "candidates" — shown as checkboxes below for
                # review, same human-confirmation principle as everything else.
                st.session_state.resume_certifications = extracted["certifications"]
                st.session_state.resume_education = extracted["education"]
                st.session_state.resume_awards = extracted["awards"]
                st.session_state.resume_publications = extracted["publications"]
                st.session_state.resume_additional_skills = extracted["additional_skills"]

                st.success(f"Extracted {total_found} item(s) across categories \u2014 "
                           "review below before continuing.")
                st.rerun()
            else:
                st.warning("Nothing found in that resume. You can still add entries manually below.")

    jobs = []
    for i in range(st.session_state.num_job_forms):
        with st.container(border=True):
            st.write(f"**Job #{i + 1}**")
            company = st.text_input("Company", key=f"company_{i}")
            title = st.text_input("Title", key=f"title_{i}")
            duration = st.text_input("Duration (e.g. 'Jan 2023 - Present')", key=f"duration_{i}")
            description = st.text_area("What you actually did", key=f"desc_{i}")
            jd = st.text_area("Job description (optional, for context only)", key=f"jd_{i}")
            if company or title or description:
                jobs.append({"company": company, "title": title, "duration": duration,
                             "description": description, "job_description": jd or None})

    if st.button("+ Add another job"):
        st.session_state.num_job_forms += 1
        st.rerun()

    # Review UI for resume-extracted certifications/education/awards/publications/
    # skills, checkbox per item so nothing is included silently.
    def review_checkboxes(label, session_key, format_fn):
        candidates = st.session_state.get(session_key, [])
        if not candidates:
            return []
        st.write(f"**{label}** (found in resume \u2014 uncheck any you don't want included)")
        kept = []
        for idx, item in enumerate(candidates):
            checked = st.checkbox(format_fn(item), value=True, key=f"{session_key}_{idx}")
            if checked:
                kept.append(item)
        return kept

    certifications = review_checkboxes(
        "Certifications", "resume_certifications",
        lambda c: c["name"] + (f" ({c['issuer']})" if c["issuer"] else ""))
    education = review_checkboxes(
        "Education", "resume_education",
        lambda e: f"{e['degree']}, {e['institution']}" + (f" ({e['year']})" if e["year"] else ""))
    awards = review_checkboxes(
        "Awards", "resume_awards",
        lambda a: a["name"] + (f" \u2014 {a['issuer']}" if a["issuer"] else ""))
    publications = review_checkboxes(
        "Publications", "resume_publications",
        lambda p: p["title"] + (f" \u2014 {p['venue']}" if p["venue"] else ""))
    additional_skills = review_checkboxes(
        "Additional skills", "resume_additional_skills", lambda s: s)

    if st.button("Continue", type="primary"):
        st.session_state.work_experience = jobs
        st.session_state.certifications = certifications
        st.session_state.education = education
        st.session_state.awards = awards
        st.session_state.publications = publications
        st.session_state.additional_skills = additional_skills
        go_to("generate")

    if st.button("Skip \u2014 nothing to add"):
        go_to("generate")

# -------------------------------------------------------------- generate ---
elif st.session_state.step == "generate":
    st.subheader("Generating your portfolio...")

    username = st.session_state.username
    phase1_path = st.session_state.phase1_path
    phase2_path = os.path.join(paths_dir, f"{username}_phase2_roles.json")
    phase3_path = os.path.join(paths_dir, f"{username}_phase3_techscan.json")
    phase4_path = os.path.join(paths_dir, f"{username}_phase4_content.json")
    portfolio_path = os.path.join(paths_dir, f"{username}_portfolio.html")

    try:
        with st.spinner("Finalizing selection and checking work experience against gaps..."):
            client = LLMClient()
            resolved_by_experience = []
            if st.session_state.work_experience and st.session_state.unresolved_gaps:
                resolved_by_experience = check_work_experience_against_gaps(
                    client, st.session_state.unresolved_gaps, st.session_state.work_experience)

            featured = compute_featured_repos(
                st.session_state.selected_names, st.session_state.gap_added_names,
                st.session_state.rankings, max_featured=10)

            phase2_output = {
                "roles": st.session_state.roles,
                "preferred_name": st.session_state.preferred_name,
                "resume_name": st.session_state.resume_name,
                "selected_repo_names": st.session_state.selected_names,
                "featured_repo_names": featured,
                "gap_added_names": st.session_state.gap_added_names,
                "unresolved_gaps": st.session_state.unresolved_gaps,
                "work_experience": st.session_state.work_experience,
                "certifications": st.session_state.certifications,
                "education": st.session_state.education,
                "awards": st.session_state.awards,
                "publications": st.session_state.publications,
                "additional_skills": st.session_state.additional_skills,
                "gaps_resolved_by_experience": resolved_by_experience,
                "all_repo_names": [r["name"] for r in st.session_state.phase1_data["repos"]],
            }
            with open(phase2_path, "w", encoding="utf-8") as f:
                json.dump(phase2_output, f, indent=2)

        with st.spinner("Running technical deep scan..."):
            run_phase3(phase1_path, phase2_path, output_path=phase3_path)

        with st.spinner("Generating bio and project descriptions..."):
            run_phase4(phase1_path, phase2_path, phase3_path, output_path=phase4_path)

        with st.spinner("Rendering portfolio..."):
            run_phase5(phase1_path, phase2_path, phase3_path, phase4_path, output_path=portfolio_path)

        st.session_state.portfolio_path = portfolio_path
        go_to("done")

    except LLMError as e:
        st.error(f"LLM error: {e}")
        if st.button("Retry"):
            st.rerun()

# ------------------------------------------------------------------ done ---
elif st.session_state.step == "done":
    st.success("Your portfolio is ready.")

    with open(st.session_state.portfolio_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    st.download_button("Download portfolio.html", data=html_content,
                        file_name="portfolio.html", mime="text/html", type="primary")

    st.subheader("Preview")
    st.iframe(html_content, height=800)

    if st.button("Start over"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()