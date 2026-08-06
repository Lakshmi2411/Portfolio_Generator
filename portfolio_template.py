"""
Phase 5: Portfolio template.

Takes the outputs of Phase 1 (profile), Phase 2 (roles, work experience),
Phase 3 (technical scan), and Phase 4 (generated content) and renders the
final portfolio as a single, self-contained HTML file — no build step, no
framework, deployable as-is to GitHub Pages/Vercel/Netlify or opened
directly in a browser.

DESIGN DIRECTION (see /mnt/skills/public/frontend-design/SKILL.md):
This person's actual body of work is about systems and pipelines — agent
orchestration, distributed backend infra, RAG retrieval — and the whole
premise of Phase 3 was surfacing real technology that isn't obvious on the
surface. Rather than a generic card-grid template, each project renders as
an inspectable "service panel": a status dot, a monospace service ID, and
an expandable readout that visualizes exactly the "hidden tech" concept
Phase 3 was built around — the design's signature element is grounded in
the project's actual thesis, not decoration bolted onto a template.

Token system:
  Color   — background #0F1417, panel #171F24, text #E8EDEF, muted #8A9BA3,
            accent (signal/teal) #4FD1C5, secondary accent (amber) #F2B84B
  Type    — display: Space Grotesk, body: IBM Plex Sans, mono: IBM Plex Mono
  Layout  — hero -> skills readout -> service-panel grid -> experience log -> footer
"""

import html
import json
import sys


def esc(text):
    return html.escape(text or "", quote=True)


def render_skills_summary(skills_summary: dict) -> str:
    all_names = sorted({n for names in skills_summary.values() for n in names})
    quick_tags = "".join(f'<span class="tag">{esc(n)}</span>' for n in all_names)

    groups_html = []
    for category, names in skills_summary.items():
        tags = "".join(f'<span class="tag">{esc(n)}</span>' for n in names)
        groups_html.append(f"""
        <div class="skill-group">
          <div class="skill-category">{esc(category)}</div>
          <div class="tag-row">{tags}</div>
        </div>""")

    return f"""
    <div class="tag-row">{quick_tags}</div>
    <details class="readout readout--skills">
      <summary>browse by category &rarr;</summary>
      {"".join(groups_html)}
    </details>"""


def render_project_panel(
    index: int, project_desc: dict, repo_meta: dict, tech_scan: dict
) -> str:
    name = project_desc["name"]
    blurb = project_desc.get("blurb", "")
    highlighted = project_desc.get("highlighted_tech", [])
    html_url = (repo_meta or {}).get("html_url", "#")
    languages = list(((repo_meta or {}).get("languages") or {}).keys())

    hidden_tech = [
        t["name"]
        for t in (tech_scan or {}).get("hidden_tech", [])
        if not t.get("environment_wide")
    ]
    all_detected = [
        t["name"]
        for t in (tech_scan or {}).get("detected_stack", [])
        if not t.get("environment_wide")
    ]

    tag_html = "".join(f'<span class="tag">{esc(t)}</span>' for t in highlighted)
    lang_html = "".join(
        f'<span class="tag tag--lang">{esc(l)}</span>' for l in languages
    )

    detected_readout = ""
    if all_detected:
        detected_list = "".join(f"<li>{esc(t)}</li>" for t in all_detected)
        hidden_note = ""
        if hidden_tech:
            hidden_note = (
                f'<p class="readout-note">Not mentioned in the README, '
                f'found by scanning dependencies: <strong>{esc(", ".join(hidden_tech))}</strong></p>'
            )
        detected_readout = f"""
        <details class="readout">
          <summary>detected stack &rarr;</summary>
          <ul class="readout-list">{detected_list}</ul>
          {hidden_note}
        </details>"""

    service_id = f"SVC/{index:02d}"

    return f"""
      <article class="panel">
        <div class="panel-head">
          <span class="status-dot"></span>
          <span class="service-id">{service_id}</span>
          <a class="panel-link" href="{esc(html_url)}" target="_blank" rel="noopener">view repo &rarr;</a>
        </div>
        <h3 class="panel-title">{esc(name)}</h3>
        <p class="panel-blurb">{esc(blurb)}</p>
        <div class="tag-row">{lang_html}{tag_html}</div>
        {detected_readout}
      </article>"""


def render_work_experience(work_experience: list, work_experience_stack: list) -> str:
    if not work_experience:
        return ""

    stack_by_company = {
        j["company"]: j.get("detected_stack", []) for j in (work_experience_stack or [])
    }

    entries = []
    for job in work_experience:
        company = job.get("company", "")
        title = job.get("title", "")
        duration = job.get("duration", "")
        description = job.get("description", "")
        tech = [t["name"] for t in stack_by_company.get(company, [])]
        tag_html = "".join(f'<span class="tag">{esc(t)}</span>' for t in tech)
        duration_html = (
            f'<span class="job-duration">{esc(duration)}</span>' if duration else ""
        )

        entries.append(f"""
        <div class="job-entry">
          <div class="job-head">
            <h3 class="job-title">{esc(title)} <span class="job-at">@ {esc(company)}</span></h3>
            {duration_html}
          </div>
          <p class="job-desc">{esc(description)}</p>
          <div class="tag-row">{tag_html}</div>
        </div>""")

    return f"""
    <section class="section">
      <div class="section-label">Experience Log</div>
      {"".join(entries)}
    </section>"""


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{name} — {title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=IBM+Plex+Sans:wght@400;500&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #0F1417;
    --panel: #171F24;
    --panel-border: #23303738;
    --text: #E8EDEF;
    --muted: #8A9BA3;
    --accent: #4FD1C5;
    --accent-2: #F2B84B;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: 'IBM Plex Sans', sans-serif;
    line-height: 1.6;
  }}
  h1, h2, h3 {{ font-family: 'Space Grotesk', sans-serif; margin: 0; }}
  a {{ color: var(--accent); }}
  .wrap {{ max-width: 880px; margin: 0 auto; padding: 64px 24px 96px; }}

  .hero {{ margin-bottom: 72px; }}
  .hero-eyebrow {{
    font-family: 'IBM Plex Mono', monospace;
    color: var(--accent);
    font-size: 13px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-bottom: 12px;
  }}
  .hero h1 {{ font-size: 40px; font-weight: 700; margin-bottom: 8px; }}
  .hero-title {{ color: var(--accent-2); font-size: 18px; margin-bottom: 24px; font-weight: 500; }}
  .hero-bio {{ color: var(--muted); font-size: 17px; max-width: 640px; }}
  .role-row {{ display: flex; gap: 8px; margin-top: 20px; flex-wrap: wrap; }}
  .role-chip {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    border: 1px solid var(--panel-border);
    color: var(--muted);
    padding: 5px 12px;
    border-radius: 3px;
  }}

  .section {{ margin-bottom: 64px; }}
  .section-label {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 13px;
    color: var(--accent);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-bottom: 20px;
    padding-bottom: 10px;
    border-bottom: 1px solid var(--panel-border);
  }}

  .skill-group {{ margin-bottom: 16px; }}
  .skill-group:last-child {{ margin-bottom: 0; }}
  .skill-category {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    color: var(--muted);
    margin-bottom: 8px;
  }}
  .readout--skills {{
    margin-top: 20px;
    padding-top: 16px;
    border-top: 1px solid var(--panel-border);
  }}
  .readout--skills[open] summary {{ margin-bottom: 16px; }}
  .tag-row {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  .tag {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    background: var(--panel);
    border: 1px solid var(--panel-border);
    color: var(--text);
    padding: 4px 10px;
    border-radius: 3px;
  }}
  .tag--lang {{ color: var(--accent-2); border-color: #F2B84B33; }}

  .panel-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  @media (max-width: 640px) {{ .panel-grid {{ grid-template-columns: 1fr; }} }}

  .panel {{
    background: var(--panel);
    border: 1px solid var(--panel-border);
    border-radius: 6px;
    padding: 20px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }}
  .panel-head {{ display: flex; align-items: center; gap: 8px; }}
  .status-dot {{
    width: 7px; height: 7px; border-radius: 50%;
    background: var(--accent);
    box-shadow: 0 0 6px var(--accent);
  }}
  .service-id {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    color: var(--muted);
    flex: 1;
  }}
  .panel-link {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    text-decoration: none;
  }}
  .panel-title {{ font-size: 19px; }}
  .panel-blurb {{ color: var(--muted); font-size: 14px; margin: 0; }}

  .readout {{ margin-top: 4px; }}
  .readout summary {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    color: var(--accent);
    cursor: pointer;
  }}
  .readout-list {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    color: var(--muted);
    columns: 2;
    margin: 10px 0 0;
    padding-left: 16px;
  }}
  .readout-note {{
    font-size: 12px;
    color: var(--accent-2);
    margin: 8px 0 0;
  }}

  .job-entry {{
    background: var(--panel);
    border: 1px solid var(--panel-border);
    border-radius: 6px;
    padding: 20px;
    margin-bottom: 16px;
  }}
  .job-head {{ display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 8px; }}
  .job-title {{ font-size: 17px; }}
  .job-at {{ color: var(--muted); font-weight: 400; font-size: 15px; }}
  .job-duration {{ font-family: 'IBM Plex Mono', monospace; font-size: 12px; color: var(--muted); }}
  .job-desc {{ color: var(--muted); font-size: 14px; margin: 10px 0; }}

  footer {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    color: var(--muted);
    text-align: center;
    padding-top: 32px;
    border-top: 1px solid var(--panel-border);
  }}
  footer a {{ color: var(--muted); }}

  :focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
  @media (prefers-reduced-motion: reduce) {{ * {{ animation: none !important; transition: none !important; }} }}
</style>
</head>
<body>
<div class="wrap">

  <section class="hero">
    <div class="hero-eyebrow">Portfolio</div>
    <h1>{name}</h1>
    <div class="hero-title">{title}</div>
    <p class="hero-bio">{bio}</p>
    <div class="role-row">{role_chips}</div>
  </section>

  <section class="section">
    <div class="section-label">Skills Readout</div>
    {skills_html}
  </section>

  <section class="section">
    <div class="section-label">Featured Projects</div>
    <div class="panel-grid">
      {projects_html}
    </div>
  </section>

  {experience_html}

  <footer>
    <a href="{github_url}" target="_blank" rel="noopener">GitHub &rarr;</a>
  </footer>

</div>
</body>
</html>"""


def run_phase5(
    phase1_path: str,
    phase2_path: str,
    phase3_path: str,
    phase4_path: str,
    output_path: str = "portfolio.html",
) -> str:
    with open(phase1_path, "r", encoding="utf-8") as f:
        phase1_data = json.load(f)
    with open(phase2_path, "r", encoding="utf-8") as f:
        phase2_data = json.load(f)
    with open(phase3_path, "r", encoding="utf-8") as f:
        phase3_data = json.load(f)
    with open(phase4_path, "r", encoding="utf-8") as f:
        phase4_data = json.load(f)

    profile = phase1_data.get("profile", {})
    repos_by_name = {r["name"]: r for r in phase1_data["repos"]}
    tech_scans_by_name = {r["name"]: r for r in phase3_data["repos"]}
    featured_names = phase2_data["featured_repo_names"]

    name = profile.get("name") or profile.get("username") or "Portfolio"
    github_url = profile.get("html_url", "#")

    role_chips = "".join(
        f'<span class="role-chip">{esc(r)}</span>' for r in phase4_data.get("roles", [])
    )
    skills_html = render_skills_summary(phase4_data.get("skills_summary", {}))

    desc_by_name = {d["name"]: d for d in phase4_data.get("project_descriptions", [])}
    projects_html = "".join(
        render_project_panel(
            i + 1, desc_by_name[n], repos_by_name.get(n), tech_scans_by_name.get(n)
        )
        for i, n in enumerate(featured_names)
        if n in desc_by_name
    )

    experience_html = render_work_experience(
        phase2_data.get("work_experience") or [],
        phase3_data.get("work_experience_stack") or [],
    )

    page = PAGE_TEMPLATE.format(
        name=esc(name),
        title=esc(phase4_data.get("suggested_title", "")),
        bio=esc(phase4_data.get("bio", "")),
        role_chips=role_chips,
        skills_html=skills_html,
        projects_html=projects_html,
        experience_html=experience_html,
        github_url=esc(github_url),
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(page)

    print(f"Saved portfolio to {output_path}")
    return output_path


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) < 4:
        p1 = input("Path to Phase 1 JSON file: ").strip()
        p2 = input("Path to Phase 2 JSON file: ").strip()
        p3 = input("Path to Phase 3 JSON file: ").strip()
        p4 = input("Path to Phase 4 JSON file: ").strip()
    else:
        p1, p2, p3, p4 = args[:4]
    run_phase5(p1, p2, p3, p4)
