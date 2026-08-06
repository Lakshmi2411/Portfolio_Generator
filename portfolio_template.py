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


# Deterministic role -> relevant tech-category keywords, used to compute the
# role-filter toggle's highlighting. No LLM call, no new judgment involved —
# just matching against categories Phase 3 already assigned to real detected
# tech, so "highlighted for this role" always traces back to genuine evidence.
ROLE_CATEGORY_HINTS = {
    "backend": {"Cloud/AWS", "Cloud/Azure", "Cloud/GCP", "Web Framework", "Database",
                "System Design", "API Design", "DevOps", "Testing", "Operations"},
    "data": {"Data Analysis", "Data Visualization", "Machine Learning", "Database",
             "NLP/ML"},
    "analyst": {"Data Analysis", "Data Visualization", "Machine Learning", "Database"},
    "ai": {"LLM Orchestration", "LLM Provider", "Machine Learning", "Deep Learning",
           "NLP/ML", "Embeddings", "Vector Database", "Vector Search"},
    "ml": {"LLM Orchestration", "LLM Provider", "Machine Learning", "Deep Learning",
           "NLP/ML", "Embeddings", "Vector Database", "Vector Search"},
    "machine learning": {"Machine Learning", "Deep Learning", "NLP/ML", "Embeddings"},
    "frontend": {"Frontend", "Web Framework"},
    "full stack": {"Frontend", "Web Framework", "Database", "API Design"},
    "devops": {"Cloud/AWS", "Cloud/Azure", "Cloud/GCP", "DevOps", "System Design", "Operations"},
    "cloud": {"Cloud/AWS", "Cloud/Azure", "Cloud/GCP", "DevOps"},
    "python": {"Machine Learning", "Data Analysis", "Web Framework", "API Design"},
}


def categories_for_role(role: str) -> set:
    role_lower = role.lower()
    matched = set()
    for keyword, categories in ROLE_CATEGORY_HINTS.items():
        if keyword in role_lower:
            matched |= categories
    return matched


def compute_role_scores(roles: list, project_categories: set) -> dict:
    """For one project, how many of its real detected-tech categories overlap
    with each role's relevant categories. Used purely for client-side
    highlighting — never claims relevance that isn't backed by an actual
    category match."""
    scores = {}
    for role in roles:
        role_categories = categories_for_role(role)
        scores[role] = len(project_categories & role_categories)
    return scores


def render_skills_summary(skills_summary: dict) -> str:
    all_names = sorted({n for names in skills_summary.values() for n in names})
    if not all_names:
        return ""  # nothing detected at all -- hide the section rather than show an empty header

    quick_tags = "".join(f'<span class="tag">{esc(n)}</span>' for n in all_names)

    groups_html = []
    for category, names in skills_summary.items():
        tags = "".join(f'<span class="tag">{esc(n)}</span>' for n in names)
        groups_html.append(f'''
        <div class="skill-group">
          <div class="skill-category">{esc(category)}</div>
          <div class="tag-row">{tags}</div>
        </div>''')

    return f'''
    <section class="section" id="skills">
      <div class="section-label">Skills Readout</div>
      <div class="tag-row">{quick_tags}</div>
      <details class="readout readout--skills">
        <summary>browse by category &rarr;</summary>
        {"".join(groups_html)}
      </details>
    </section>'''


def render_project_panel(index: int, project_desc: dict, repo_meta: dict, tech_scan: dict, roles: list) -> str:
    name = project_desc["name"]
    blurb = project_desc.get("blurb", "")
    highlighted = project_desc.get("highlighted_tech", [])
    html_url = (repo_meta or {}).get("html_url", "#")
    languages = list(((repo_meta or {}).get("languages") or {}).keys())

    hidden_tech = [t["name"] for t in (tech_scan or {}).get("hidden_tech", []) if not t.get("environment_wide")]
    all_detected_tech = [t for t in (tech_scan or {}).get("detected_stack", []) if not t.get("environment_wide")]
    all_detected = [t["name"] for t in all_detected_tech]
    project_categories = {t["category"] for t in all_detected_tech}

    role_scores = compute_role_scores(roles, project_categories)
    role_scores_json = esc(json.dumps(role_scores))

    tag_html = "".join(f'<span class="tag">{esc(t)}</span>' for t in highlighted)
    lang_html = "".join(f'<span class="tag tag--lang">{esc(l)}</span>' for l in languages)

    detected_readout = ""
    if all_detected:
        detected_list = "".join(f"<li>{esc(t)}</li>" for t in all_detected)
        hidden_note = ""
        if hidden_tech:
            hidden_note = (f'<p class="readout-note">Not mentioned in the README, '
                            f'found by scanning dependencies: <strong>{esc(", ".join(hidden_tech))}</strong></p>')
        detected_readout = f'''
        <details class="readout">
          <summary>detected stack &rarr;</summary>
          <ul class="readout-list">{detected_list}</ul>
          {hidden_note}
        </details>'''

    service_id = f"SVC/{index:02d}"

    return f'''
      <article class="panel" data-role-scores="{role_scores_json}">
        <div class="panel-head">
          <span class="status-dot"></span>
          <span class="service-id">{service_id}</span>
          <a class="panel-link" href="{esc(html_url)}" target="_blank" rel="noopener">view repo &rarr;</a>
        </div>
        <h3 class="panel-title">{esc(name)}</h3>
        <p class="panel-blurb">{esc(blurb)}</p>
        <div class="tag-row">{lang_html}{tag_html}</div>
        {detected_readout}
      </article>'''


def build_chat_context(name: str, roles: list, bio: str, project_descriptions: list,
                        skills_summary: dict, work_experience: list, certifications: list,
                        education: list, awards: list) -> dict:
    """
    Everything the chat widget's serverless backend needs to answer questions
    grounded in real portfolio content — nothing here is new information, it's
    all already visible elsewhere on the page. Kept compact (names/blurbs, not
    full READMEs) since this gets embedded directly in the HTML and sent with
    every chat request.
    """
    return {
        "name": name,
        "roles": roles,
        "bio": bio,
        "projects": [
            {"name": p["name"], "summary": p.get("blurb", ""), "tech": p.get("highlighted_tech", [])}
            for p in project_descriptions
        ],
        "skills": sorted({n for names in skills_summary.values() for n in names}),
        "work_experience": [
            {"company": j.get("company", ""), "title": j.get("title", ""),
             "duration": j.get("duration", ""), "summary": j.get("description", "")}
            for j in work_experience
        ],
        "certifications": [c.get("name", "") for c in certifications],
        "education": [f"{e.get('degree', '')}, {e.get('institution', '')}" for e in education],
        "awards": [a.get("name", "") for a in awards],
    }


def render_chat_widget(name: str, context: dict) -> str:
    first_name = (name or "").split(" ")[0] or "this person"
    # Embedded as JSON, not re-escaped as HTML text — this is data for JS to
    # read, not markup. "</script>" can't appear inside legitimate JSON string
    # content unescaped, but guard against it anyway since this includes
    # free-text bios/descriptions.
    context_json = json.dumps(context).replace("</", "<\\/")

    return f'''
    <section class="section" id="chat">
      <div class="section-label">Ask About This Portfolio</div>
      <div class="chat-panel">
        <div class="chat-log" id="chatLog">
          <div class="chat-msg chat-msg--bot">
            Ask me anything about {esc(first_name)}'s projects or experience.
          </div>
        </div>
        <form class="chat-input-row" id="chatForm">
          <input type="text" id="chatInput" class="chat-input" placeholder="e.g. What's their strongest backend project?" autocomplete="off">
          <button type="submit" class="chat-send">Send</button>
        </form>
      </div>
    </section>
    <script id="portfolio-chat-context" type="application/json">{context_json}</script>'''


def _cred_line(primary, secondary=None, date=None):
    line = esc(primary)
    if secondary:
        line += " — " + esc(secondary)
    if date:
        line += " (" + esc(date) + ")"
    return f"<li>{line}</li>"


def render_credentials(certifications: list, education: list, awards: list,
                        publications: list, additional_skills: list) -> str:
    """Renders whatever resume-derived credentials exist. Each sub-section only
    appears if that category actually has content — no empty headers."""
    if not any([certifications, education, awards, publications, additional_skills]):
        return ""

    blocks = []

    if certifications:
        items = "".join(_cred_line(c["name"], c.get("issuer"), c.get("date")) for c in certifications)
        blocks.append(f'<div class="cred-group"><div class="cred-label">Certifications</div><ul class="cred-list">{items}</ul></div>')

    if education:
        items = "".join(_cred_line(f"{e['degree']}, {e['institution']}", date=e.get("year")) for e in education)
        blocks.append(f'<div class="cred-group"><div class="cred-label">Education</div><ul class="cred-list">{items}</ul></div>')

    if awards:
        items = "".join(_cred_line(a["name"], a.get("issuer"), a.get("date")) for a in awards)
        blocks.append(f'<div class="cred-group"><div class="cred-label">Awards</div><ul class="cred-list">{items}</ul></div>')

    if publications:
        items = "".join(_cred_line(p["title"], p.get("venue"), p.get("date")) for p in publications)
        blocks.append(f'<div class="cred-group"><div class="cred-label">Publications</div><ul class="cred-list">{items}</ul></div>')

    if additional_skills:
        tags = "".join(f'<span class="tag">{esc(s)}</span>' for s in additional_skills)
        blocks.append(f'<div class="cred-group"><div class="cred-label">Additional Skills</div><div class="tag-row">{tags}</div></div>')

    return f'''
    <section class="section" id="credentials">
      <div class="section-label">Credentials</div>
      <div class="cred-grid">{"".join(blocks)}</div>
    </section>'''


def render_work_experience(work_experience: list, work_experience_stack: list) -> str:
    if not work_experience:
        return ""

    stack_by_company = {j["company"]: j.get("detected_stack", []) for j in (work_experience_stack or [])}

    entries = []
    for job in work_experience:
        company = job.get("company", "")
        title = job.get("title", "")
        duration = job.get("duration", "")
        description = job.get("description", "")
        tech = [t["name"] for t in stack_by_company.get(company, [])]
        tag_html = "".join(f'<span class="tag">{esc(t)}</span>' for t in tech)
        duration_html = f'<span class="job-duration">{esc(duration)}</span>' if duration else ""

        entries.append(f'''
        <div class="job-entry">
          <div class="job-head">
            <h3 class="job-title">{esc(title)} <span class="job-at">@ {esc(company)}</span></h3>
            {duration_html}
          </div>
          <p class="job-desc">{esc(description)}</p>
          <div class="tag-row">{tag_html}</div>
        </div>''')

    return f'''
    <section class="section" id="experience">
      <div class="section-label">Experience Log</div>
      {"".join(entries)}
    </section>'''


PAGE_TEMPLATE = '''<!DOCTYPE html>
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
  html {{ scroll-behavior: smooth; }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: 'IBM Plex Sans', sans-serif;
    line-height: 1.6;
  }}
  h1, h2, h3 {{ font-family: 'Space Grotesk', sans-serif; margin: 0; }}
  a {{ color: var(--accent); }}
  .wrap {{ max-width: 880px; margin: 0 auto; padding: 24px 24px 96px; }}
  section[id] {{ scroll-margin-top: 76px; }}

  .site-nav {{
    position: sticky;
    top: 0;
    z-index: 10;
    display: flex;
    gap: 20px;
    padding: 14px 0;
    margin-bottom: 40px;
    background: rgba(15, 20, 23, 0.92);
    backdrop-filter: blur(6px);
    border-bottom: 1px solid var(--panel-border);
  }}
  .site-nav a {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    color: var(--muted);
    text-decoration: none;
    letter-spacing: 0.04em;
  }}
  .site-nav a:hover {{ color: var(--accent); }}

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
    background: transparent;
    border: 1px solid var(--panel-border);
    color: var(--muted);
    padding: 5px 12px;
    border-radius: 3px;
    cursor: pointer;
  }}
  .role-chip:hover {{ border-color: var(--accent); color: var(--text); }}
  .role-chip.active {{ border-color: var(--accent); color: var(--accent); background: #4FD1C51A; }}

  .panel {{ transition: opacity 0.15s ease, border-color 0.15s ease; }}
  .panel.is-dimmed {{ opacity: 0.35; }}
  .panel.is-match {{ border-color: var(--accent); }}

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

  .preview-badge {{
    font-size: 10px;
    color: var(--bg);
    background: var(--accent-2);
    padding: 2px 6px;
    border-radius: 3px;
    margin-left: 8px;
    letter-spacing: 0.02em;
    vertical-align: middle;
  }}
  .chat-panel {{
    background: var(--panel);
    border: 1px solid var(--panel-border);
    border-radius: 6px;
    padding: 16px;
  }}
  .chat-log {{
    display: flex;
    flex-direction: column;
    gap: 10px;
    max-height: 280px;
    overflow-y: auto;
    margin-bottom: 12px;
  }}
  .chat-msg {{
    font-size: 14px;
    padding: 10px 14px;
    border-radius: 6px;
    max-width: 85%;
  }}
  .chat-msg--bot {{ background: #1E2830; color: var(--text); align-self: flex-start; }}
  .chat-msg--user {{ background: #4FD1C51A; color: var(--text); align-self: flex-end; }}
  .chat-note {{ display: block; font-size: 11px; color: var(--muted); margin-top: 6px; }}
  .chat-input-row {{ display: flex; gap: 8px; }}
  .chat-input {{
    flex: 1;
    background: var(--bg);
    border: 1px solid var(--panel-border);
    border-radius: 4px;
    color: var(--text);
    padding: 10px 12px;
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 14px;
  }}
  .chat-input:focus {{ outline: none; border-color: var(--accent); }}
  .chat-send {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    background: var(--accent);
    color: var(--bg);
    border: none;
    border-radius: 4px;
    padding: 0 18px;
    cursor: pointer;
    font-weight: 500;
  }}
  .chat-send:hover {{ opacity: 0.9; }}

  .cred-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
  @media (max-width: 640px) {{ .cred-grid {{ grid-template-columns: 1fr; }} }}
  .cred-group {{
    background: var(--panel);
    border: 1px solid var(--panel-border);
    border-radius: 6px;
    padding: 16px 20px;
  }}
  .cred-label {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    color: var(--accent);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 10px;
  }}
  .cred-list {{ margin: 0; padding-left: 18px; font-size: 14px; color: var(--text); }}
  .cred-list li {{ margin-bottom: 6px; }}

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

  <nav class="site-nav">
    {skills_nav_link}
    <a href="#projects">Projects</a>
    {experience_nav_link}
    {credentials_nav_link}
    <a href="#chat">Ask</a>
  </nav>

  <section class="hero">
    <div class="hero-eyebrow">Portfolio</div>
    <h1>{name}</h1>
    <div class="hero-title">{title}</div>
    <p class="hero-bio">{bio}</p>
    <div class="role-row" id="roleFilter">{role_chips}</div>
  </section>

  {skills_html}

  <section class="section" id="projects">
    <div class="section-label">Featured Projects</div>
    <div class="panel-grid" id="panelGrid">
      {projects_html}
    </div>
  </section>

  {experience_html}

  {credentials_html}

  {chat_html}

  <footer>
    <a href="{github_url}" target="_blank" rel="noopener">GitHub &rarr;</a>
  </footer>

</div>

<script>
  // Role filter: highlights projects whose real detected-tech categories
  // overlap with the selected role (see compute_role_scores in Python —
  // this only reads pre-computed data, no invented relevance).
  (function() {{
    var chips = document.querySelectorAll('.role-chip');
    var panels = document.querySelectorAll('#panelGrid .panel');
    chips.forEach(function(chip) {{
      chip.addEventListener('click', function() {{
        var role = chip.dataset.role;
        var isActive = chip.classList.contains('active');
        chips.forEach(function(c) {{ c.classList.remove('active'); }});
        panels.forEach(function(p) {{ p.classList.remove('is-dimmed', 'is-match'); }});
        if (isActive) return; // clicking the active chip again clears the filter
        chip.classList.add('active');
        panels.forEach(function(p) {{
          var scores = JSON.parse(p.dataset.roleScores || '{{}}');
          if ((scores[role] || 0) > 0) {{
            p.classList.add('is-match');
          }} else {{
            p.classList.add('is-dimmed');
          }}
        }});
      }});
    }});
  }})();

  // Chat widget: calls a serverless /api/chat endpoint (see api/chat.js —
  // deploy it alongside this page, e.g. on Vercel) so the API key stays
  // server-side and is never exposed in this HTML. Answers are grounded in
  // the portfolio-chat-context JSON embedded above — same data already
  // visible elsewhere on this page, nothing new is exposed by including it.
  (function() {{
    var form = document.getElementById('chatForm');
    if (!form) return;
    var input = document.getElementById('chatInput');
    var log = document.getElementById('chatLog');
    var sendBtn = form.querySelector('.chat-send');
    var contextEl = document.getElementById('portfolio-chat-context');
    var context = contextEl ? JSON.parse(contextEl.textContent) : {{}};

    function addMessage(text, who) {{
      var msg = document.createElement('div');
      msg.className = 'chat-msg chat-msg--' + who;
      msg.textContent = text;
      log.appendChild(msg);
      log.scrollTop = log.scrollHeight;
      return msg;
    }}

    form.addEventListener('submit', function(e) {{
      e.preventDefault();
      var text = input.value.trim();
      if (!text) return;
      addMessage(text, 'user');
      input.value = '';
      sendBtn.disabled = true;
      var thinking = addMessage('...', 'bot');

      fetch('/api/chat', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ message: text, context: context }})
      }})
        .then(function(res) {{
          if (!res.ok) throw new Error('status ' + res.status);
          return res.json();
        }})
        .then(function(data) {{
          thinking.textContent = data.reply || "Sorry, I didn't get a response.";
        }})
        .catch(function() {{
          thinking.textContent = "Chat isn't available right now \u2014 this page needs the " +
            "api/chat serverless function deployed alongside it (see api/chat.js).";
        }})
        .finally(function() {{
          sendBtn.disabled = false;
          log.scrollTop = log.scrollHeight;
        }});
    }});
  }})();
</script>
</body>
</html>'''


def run_phase5(phase1_path: str, phase2_path: str, phase3_path: str, phase4_path: str,
               output_path: str = "portfolio.html") -> str:
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

    # Name resolution priority: explicit override the person typed > GitHub's
    # own display name > name extracted from an uploaded resume > GitHub
    # username as a last resort. Reading from phase2_data since that's where
    # both the preferred_name prompt and resume parsing write their results.
    name = (
        phase2_data.get("preferred_name")
        or profile.get("name")
        or phase2_data.get("resume_name")
        or profile.get("username")
        or "Portfolio"
    )
    github_url = profile.get("html_url", "#")
    roles = phase4_data.get("roles", [])

    role_chips = "".join(
        f'<button type="button" class="role-chip" data-role="{esc(r)}">{esc(r)}</button>' for r in roles
    )
    skills_html = render_skills_summary(phase4_data.get("skills_summary", {}))
    skills_nav_link = '<a href="#skills">Skills</a>' if skills_html else ""

    desc_by_name = {d["name"]: d for d in phase4_data.get("project_descriptions", [])}
    projects_html = "".join(
        render_project_panel(i + 1, desc_by_name[n], repos_by_name.get(n), tech_scans_by_name.get(n), roles)
        for i, n in enumerate(featured_names) if n in desc_by_name
    )

    work_experience = phase2_data.get("work_experience") or []
    experience_html = render_work_experience(work_experience, phase3_data.get("work_experience_stack") or [])
    experience_nav_link = '<a href="#experience">Experience</a>' if work_experience else ""

    certifications = phase4_data.get("certifications") or []
    education = phase4_data.get("education") or []
    awards = phase4_data.get("awards") or []
    publications = phase4_data.get("publications") or []
    additional_skills = phase4_data.get("additional_skills") or []
    credentials_html = render_credentials(certifications, education, awards, publications, additional_skills)
    credentials_nav_link = '<a href="#credentials">Credentials</a>' if credentials_html else ""

    chat_context = build_chat_context(
        name, roles, phase4_data.get("bio", ""), phase4_data.get("project_descriptions", []),
        phase4_data.get("skills_summary", {}), work_experience, certifications, education, awards,
    )
    chat_html = render_chat_widget(name, chat_context)

    page = PAGE_TEMPLATE.format(
        name=esc(name),
        title=esc(phase4_data.get("suggested_title", "")),
        bio=esc(phase4_data.get("bio", "")),
        role_chips=role_chips,
        skills_html=skills_html,
        skills_nav_link=skills_nav_link,
        projects_html=projects_html,
        experience_html=experience_html,
        experience_nav_link=experience_nav_link,
        credentials_html=credentials_html,
        credentials_nav_link=credentials_nav_link,
        chat_html=chat_html,
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