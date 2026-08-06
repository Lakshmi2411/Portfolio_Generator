
# Portfolio Generator

Turn a GitHub profile into a **role-targeted, interactive portfolio**.

This tool does more than list repositories. It:

- asks what role(s) you’re targeting
- ranks your repos by relevance to those roles
- lets you confirm or override the AI’s suggestions
- detects real technologies from dependency files (not just README text)
- generates grounded project descriptions and a professional bio
- renders a self-contained interactive HTML portfolio

Built for developers who want a portfolio that reflects both public GitHub work and real professional experience.

---

## Why this exists

Most GitHub-based portfolio tools:

- rank projects by stars
- rewrite README text generically
- ignore work experience not visible on GitHub
- invent skills or achievements

This project is designed differently:

| Principle | How it’s applied |
|------|------|
| **Role-aware** | Projects are ranked and framed for target job roles |
| **Human-in-the-loop** | You confirm repo selection, gap fills, resume items, and experience |
| **Grounded generation** | Content is based only on fetched data, detected tech, and your own inputs |
| **Hidden tech detection** | Dependency files reveal real stack depth that READMEs often undersell |
| **Experience-aware** | Work history, certifications, education, and awards can strengthen the portfolio |

---

## Architecture

```text
GitHub username
      │
      ▼
Phase 1  Fetch profile, repos, READMEs, dependency files
      │
      ▼
Phase 2  Target roles → AI ranking → user selection → gap analysis
         optional work experience + resume upload
      │
      ▼
Phase 3  Technical deep scan of dependency manifests
      │
      ▼
Phase 4  Generate bio, project blurbs, skills summary
      │
      ▼
Phase 5  Render interactive portfolio HTML
      │
      ▼
Phase 6  Streamlit UI wraps the full flow
```

### Core modules

| File | Role |
|------|------|
| `github_fetcher.py` | GitHub API fetching |
| `role_selection.py` | Role targeting, ranking, gap analysis |
| `technical_scan.py` | Dependency parsing + tech detection |
| `content_generation.py` | Bio + project description generation |
| `portfolio_template.py` | Interactive HTML portfolio renderer |
| `resume_parser.py` | Optional resume extraction |
| `orchestrator.py` | CLI end-to-end pipeline |
| `app.py` | Streamlit product UI |
| `chat.js` | Optional serverless chat backend for deployed portfolios |

---

## Features

### Role-targeted project selection
Enter up to 3 target roles. The system ranks repositories by relevance and suggests a selection. You can accept or override it.

### Gap analysis
Identifies missing portfolio signals for the target roles and checks whether existing repos (or work experience) already fill them.

### Technical deep scan
Parses files such as:
- `requirements.txt`
- `package.json`
- `pyproject.toml`

Then maps packages to meaningful technologies using a curated dictionary.

This is how a project described as “chat with PDF” can be correctly recognized as a hybrid RAG system using tools like LangChain, FAISS, or ChromaDB.

### Grounded content generation
- Project blurbs use README evidence + detected tech
- Bio uses profile data, selected projects, and user-provided experience
- Skills are aggregated deterministically from real detections

### Optional resume upload
Upload a PDF/DOCX/TXT resume to extract:
- jobs
- certifications
- education
- awards
- publications
- additional skills

Nothing is added silently — you review and confirm.

### Interactive portfolio output
A single self-contained HTML file with:
- role chips
- skills readout
- expandable project panels
- detected-stack insights
- experience section
- optional chat widget hook

---

## Setup

```bash
git clone https://github.com/Lakshmi2411/Portfolio_Generator.git
cd Portfolio_Generator

python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Create a `.env` file:

```env
GROQ_API_KEY=your_groq_api_key
GITHUB_TOKEN=your_github_token   # optional, but recommended for higher rate limits
```

- **Groq** is used for ranking and content generation
- **GitHub token** improves API limits when fetching repos/READMEs/dependencies

---

## Usage

### Option A: Streamlit UI (recommended)

```bash
streamlit run app.py
```

Flow:
1. Enter GitHub username
2. Enter target role(s)
3. Confirm ranked project selection
4. Review gap suggestions
5. Optionally add work experience / upload resume
6. Generate and download portfolio HTML

### Option B: CLI pipeline

```bash
python orchestrator.py <github_username>
```

This runs Phases 1–5 and writes intermediate JSON files plus the final HTML portfolio.

---

## Output

The generator produces:

- `{username}_phase1_github.json`
- `{username}_phase2_roles.json`
- `{username}_phase3_techscan.json`
- `{username}_phase4_content.json`
- `{username}_portfolio.html`

The HTML file is self-contained and can be opened locally or deployed to:
- GitHub Pages
- Netlify
- Vercel

---

## Optional: Chat on the deployed portfolio

The portfolio can include an “Ask about this portfolio” widget.

Important:
- Do **not** put API keys in the frontend
- Use the provided serverless function in `chat.js`

### Deploy idea (Vercel)
1. Deploy the generated portfolio HTML
2. Add `api/chat.js`
3. Set `GROQ_API_KEY` in Vercel environment variables

The chat backend answers only from portfolio context (bio, projects, tech, experience) and is instructed not to invent missing information.

---

## Design principles

### 1. Human confirmation at decision points
AI can rank and suggest, but the user confirms:
- which repos to feature
- whether to add gap-fill repos
- whether resume-extracted items should be included

### 2. No invented achievements
Content generation is constrained to:
- GitHub profile/repo evidence
- dependency-detected technologies
- user-provided experience and resume text

### 3. Real stack over marketing language
If dependencies show FAISS, ChromaDB, LangGraph, CrewAI, etc., the portfolio should say so — even when the README is understated.

### 4. Role framing without distortion
Descriptions are angled toward the target role, but only where the evidence supports it.

---

## Project status

Completed:
- [x] GitHub data fetching
- [x] Role-aware ranking and selection
- [x] Gap analysis
- [x] Technical dependency scan
- [x] Content generation
- [x] Interactive HTML portfolio
- [x] Streamlit UI
- [x] Resume parsing
- [x] Chat backend stub for public deployment

Possible future improvements:
- [ ] Stronger rate limiting / abuse protection for public chat
- [ ] More interactive portfolio filters
- [ ] One-click deploy helpers
- [ ] Richer education/certification presentation

---

## Example use cases

- Backend engineer highlighting production systems + cloud experience
- AI engineer showcasing RAG, agents, and tool-calling projects
- Data analyst combining notebooks, SQL work, and analytics apps
- Career transition portfolios where GitHub alone underrepresents real experience

---

## License

MIT
```

---


