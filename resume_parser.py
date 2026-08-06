"""
Resume parser — an alternative (not replacement) way to add work experience
in Phase 2. Manual typing still works; this lets someone upload a resume
instead of retyping what's already written down.

Two-stage pipeline, deliberately kept separate:
  1. Text extraction (pypdf / python-docx) — purely mechanical, no AI involved.
  2. LLM structuring — turns raw resume text into {company, title, duration,
     description} entries.

ANTI-HALLUCINATION GUARDRAIL (same pattern as ai-resume-cover-letter and
every other content-generation step in this project): the model is told to
extract ONLY what's literally present in the resume text — never invent a
company, title, date, or achievement. Whatever comes out still goes through
the same human-confirmation screen as manually-typed entries before it's
used anywhere — this parser proposes, it never finalizes silently.
"""

import json
import os
from typing import Optional

from llm_client import LLMClient, LLMError


class ResumeParseError(Exception):
    pass


# ---------- text extraction (deterministic, no AI) ----------

def extract_text_from_pdf(path: str) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ResumeParseError("pypdf is required to read PDF resumes. Install with: pip install pypdf")

    reader = PdfReader(path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def extract_text_from_docx(path: str) -> str:
    try:
        import docx
    except ImportError:
        raise ResumeParseError("python-docx is required to read DOCX resumes. Install with: pip install python-docx")

    doc = docx.Document(path)
    return "\n".join(p.text for p in doc.paragraphs)


def extract_text_from_txt(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def extract_resume_text(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return extract_text_from_pdf(path)
    elif ext == ".docx":
        return extract_text_from_docx(path)
    elif ext in (".txt", ".md"):
        return extract_text_from_txt(path)
    else:
        raise ResumeParseError(f"Unsupported resume file type '{ext}'. Use PDF, DOCX, or TXT.")


# ---------- AI structuring ----------

RESUME_PARSE_SYSTEM_PROMPT = """You are extracting structured information from a resume's raw text,
across several categories: work experience, certifications/credentials, education, awards/honors,
publications, and any additional skills mentioned that go beyond what a GitHub profile would show
(e.g. languages spoken, domain knowledge, tools, soft skills explicitly named in the resume).

CRITICAL GROUNDING RULE: only extract items LITERALLY present in the resume text. Never invent,
guess, or embellish a company, title, date, degree, institution, award name, publication, or skill.
If a date isn't clearly stated, leave it as an empty string rather than guessing. Summarize each
role's actual responsibilities as stated in the resume — don't add detail or metrics that aren't
there. Only extract additional_skills that are explicitly named in the resume text itself, not
implied or inferred.

IMPORTANT for job descriptions specifically: preserve the SPECIFIC named tools, platforms, and
technologies mentioned in the resume's bullet points — do not generalize them away into vaguer
language. For example, if the resume says "leveraged GitHub Copilot and Databricks Genie to
accelerate development," keep those tool names in the description rather than writing something
generic like "used AI-driven development tools." A later step matches real technologies by name
against this description text, so paraphrasing a named tool into a generic category makes that
tool invisible downstream even though the resume explicitly states it. Summarize the narrative
flow, but keep every named tool/technology/platform intact.

Always respond with valid JSON only, no markdown fences, no commentary."""

RESUME_PARSE_USER_PROMPT_TEMPLATE = """Resume text:
{resume_text}

Return a JSON object with this exact shape:
{{
  "name": "<the candidate's full name as stated on the resume, or empty string if unclear>",
  "jobs": [
    {{"company": "<company name>", "title": "<job title>", "duration": "<date range, or empty string if unclear>",
      "description": "<what they did — summarize the narrative, but keep every named tool/technology from the original bullet points intact, don't generalize them away>"}}
  ],
  "certifications": [
    {{"name": "<certification/credential name>", "issuer": "<issuing organization, or empty string if unclear>",
      "date": "<date obtained, or empty string if unclear>"}}
  ],
  "education": [
    {{"degree": "<degree/qualification>", "institution": "<school name>", "year": "<year, or empty string if unclear>"}}
  ],
  "awards": [
    {{"name": "<award/honor name>", "issuer": "<who gave it, or empty string if unclear>", "date": "<date, or empty string if unclear>"}}
  ],
  "publications": [
    {{"title": "<publication title>", "venue": "<where published, or empty string if unclear>", "date": "<date, or empty string if unclear>"}}
  ],
  "additional_skills": ["<skill or capability explicitly named in the resume, not already obvious from GitHub tech>"]
}}
Extract every distinct item found per category. If a category has nothing, return an empty list for it."""


def parse_resume(client: LLMClient, resume_text: str, max_chars: int = 12000) -> dict:
    """Returns a dict with name, jobs, certifications, education, awards,
    publications, and additional_skills — all ready to show the user for
    confirmation/editing, never used directly without human review."""
    empty = {"name": "", "jobs": [], "certifications": [], "education": [], "awards": [],
             "publications": [], "additional_skills": []}
    if not resume_text.strip():
        return empty

    truncated = resume_text[:max_chars]
    prompt = RESUME_PARSE_USER_PROMPT_TEMPLATE.format(resume_text=truncated)
    result = client.chat_json(RESUME_PARSE_SYSTEM_PROMPT, prompt, temperature=0.0, max_tokens=3072)

    name = result.get("name", "") or ""
    jobs = [
        {
            "company": j.get("company", ""),
            "title": j.get("title", ""),
            "duration": j.get("duration", ""),
            "description": j.get("description", ""),
            "job_description": None,
        }
        for j in result.get("jobs", [])
    ]
    certifications = [
        {"name": c.get("name", ""), "issuer": c.get("issuer", ""), "date": c.get("date", "")}
        for c in result.get("certifications", [])
    ]
    education = [
        {"degree": e.get("degree", ""), "institution": e.get("institution", ""), "year": e.get("year", "")}
        for e in result.get("education", [])
    ]
    awards = [
        {"name": a.get("name", ""), "issuer": a.get("issuer", ""), "date": a.get("date", "")}
        for a in result.get("awards", [])
    ]
    publications = [
        {"title": p.get("title", ""), "venue": p.get("venue", ""), "date": p.get("date", "")}
        for p in result.get("publications", [])
    ]
    additional_skills = [s for s in result.get("additional_skills", []) if s]

    return {
        "name": name, "jobs": jobs, "certifications": certifications, "education": education,
        "awards": awards, "publications": publications, "additional_skills": additional_skills,
    }


def parse_resume_to_jobs(client: LLMClient, resume_text: str, max_chars: int = 12000) -> list:
    """Back-compat wrapper — jobs only. Prefer parse_resume() for new code
    since it extracts everything else in the same call at no extra cost."""
    return parse_resume(client, resume_text, max_chars)["jobs"]


def parse_resume_file(client: LLMClient, path: str) -> dict:
    text = extract_resume_text(path)
    return parse_resume(client, text)