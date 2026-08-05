"""
Phase 1: GitHub Data Ingestion
--------------------------------
Fetches everything the later phases will need for ONE GitHub user:
  - profile info
  - repo list (with stars, topics, last updated, etc.)
  - per-repo language breakdown
  - per-repo README (decoded)
  - per-repo dependency/manifest files (package.json, requirements.txt, etc.)
    -> this is the raw material Phase 3 (technical deep scan) will use to
       detect real tech (e.g. an LLM library) even if the README never
       mentions it.

100% free: uses only the public GitHub REST API.
  - Unauthenticated: 60 requests/hour (fine for testing)
  - With a free GitHub Personal Access Token: 5,000 requests/hour
    Set env var GITHUB_TOKEN to use one. No paid tier required.
"""

import base64
import os
import time
import json
from dataclasses import dataclass, field, asdict
from typing import Optional

import requests
from dotenv import load_dotenv

# Loads variables from a .env file in the project root into os.environ.
# Create a file named ".env" (never commit it) containing:
#   GITHUB_TOKEN=ghp_your_token_here
load_dotenv()

GITHUB_API = "https://api.github.com"

# Manifest/dependency files we look for in each repo's root.
# This list drives Phase 3's tech-detection step later.
DEPENDENCY_FILES = [
    "package.json",  # JS/Node
    "requirements.txt",  # Python
    "pyproject.toml",  # Python (poetry/modern)
    "Pipfile",  # Python (pipenv)
    "Cargo.toml",  # Rust
    "go.mod",  # Go
    "pom.xml",  # Java (Maven)
    "build.gradle",  # Java/Kotlin (Gradle)
    "Gemfile",  # Ruby
    "composer.json",  # PHP
]


class GitHubAPIError(Exception):
    """Raised when the GitHub API returns an error we can't recover from."""

    pass


class RateLimitError(GitHubAPIError):
    """Raised when we hit GitHub's rate limit."""

    pass


@dataclass
class RepoData:
    name: str
    full_name: str
    description: Optional[str]
    html_url: str
    stargazers_count: int
    forks_count: int
    is_fork: bool
    is_archived: bool
    topics: list = field(default_factory=list)
    languages: dict = field(
        default_factory=dict
    )  # {"Python": 12345, ...} bytes per language
    readme_text: Optional[str] = None
    dependency_files: dict = field(
        default_factory=dict
    )  # {"requirements.txt": "flask\n..."}
    pushed_at: Optional[str] = None
    created_at: Optional[str] = None


@dataclass
class UserProfile:
    username: str
    name: Optional[str]
    bio: Optional[str]
    avatar_url: Optional[str]
    public_repos: int
    followers: int
    html_url: str


class GitHubFetcher:
    def __init__(self, token: Optional[str] = None, request_delay: float = 0.0):
        """
        token: optional GitHub Personal Access Token (free to create,
               just needs public_repo / read-only scope). Raises the
               rate limit from 60/hr to 5000/hr.
        request_delay: seconds to sleep between requests, useful if you're
               close to the rate limit and want to slow down deliberately.
        """
        self.session = requests.Session()
        self.token = token or os.environ.get("GITHUB_TOKEN")
        headers = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        self.session.headers.update(headers)
        self.request_delay = request_delay

    # ---------- low-level helpers ----------

    def _get(self, url: str, params: dict = None) -> requests.Response:
        if self.request_delay:
            time.sleep(self.request_delay)
        resp = self.session.get(url, params=params)

        if resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
            reset = int(resp.headers.get("X-RateLimit-Reset", 0))
            wait = max(0, reset - int(time.time()))
            raise RateLimitError(
                f"GitHub rate limit hit. Resets in ~{wait}s. "
                f"Tip: set GITHUB_TOKEN (free) to raise the limit to 5000/hr."
            )
        if resp.status_code == 404:
            raise GitHubAPIError(f"Not found: {url}")
        if not resp.ok:
            raise GitHubAPIError(
                f"GitHub API error {resp.status_code} for {url}: {resp.text[:200]}"
            )
        return resp

    def rate_limit_status(self) -> dict:
        """Check remaining quota without consuming much of it."""
        resp = self._get(f"{GITHUB_API}/rate_limit")
        return resp.json()["resources"]["core"]

    # ---------- profile ----------

    def get_user_profile(self, username: str) -> UserProfile:
        resp = self._get(f"{GITHUB_API}/users/{username}")
        data = resp.json()
        return UserProfile(
            username=data["login"],
            name=data.get("name"),
            bio=data.get("bio"),
            avatar_url=data.get("avatar_url"),
            public_repos=data.get("public_repos", 0),
            followers=data.get("followers", 0),
            html_url=data.get("html_url", ""),
        )

    # ---------- repos ----------

    def get_user_repos(
        self, username: str, include_forks: bool = False, max_repos: int = 100
    ) -> list:
        """Fetch the user's public repos, most recently pushed first."""
        repos = []
        page = 1
        while len(repos) < max_repos:
            resp = self._get(
                f"{GITHUB_API}/users/{username}/repos",
                params={
                    "per_page": 100,
                    "page": page,
                    "sort": "pushed",
                    "direction": "desc",
                },
            )
            batch = resp.json()
            if not batch:
                break
            for r in batch:
                if not include_forks and r.get("fork"):
                    continue
                repos.append(r)
            page += 1
            if len(batch) < 100:
                break
        return repos[:max_repos]

    def get_repo_languages(self, owner: str, repo: str) -> dict:
        resp = self._get(f"{GITHUB_API}/repos/{owner}/{repo}/languages")
        return resp.json()

    def get_repo_readme(self, owner: str, repo: str) -> Optional[str]:
        try:
            resp = self._get(f"{GITHUB_API}/repos/{owner}/{repo}/readme")
        except GitHubAPIError:
            return None
        data = resp.json()
        content = data.get("content", "")
        if not content:
            return None
        try:
            return base64.b64decode(content).decode("utf-8", errors="replace")
        except Exception:
            return None

    def get_file_content(self, owner: str, repo: str, path: str) -> Optional[str]:
        """Fetch a single file's raw text content, or None if it doesn't exist."""
        try:
            resp = self._get(f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}")
        except GitHubAPIError:
            return None
        data = resp.json()
        if isinstance(data, list):  # path was a directory, not a file
            return None
        content = data.get("content", "")
        if not content:
            return None
        try:
            return base64.b64decode(content).decode("utf-8", errors="replace")
        except Exception:
            return None

    def get_dependency_files(self, owner: str, repo: str) -> dict:
        """
        Pull known manifest files from the repo root.
        This is raw material for Phase 3's technical deep scan
        (e.g. spotting 'openai' or 'langchain' in requirements.txt
        even if the README just says "a chatbot").

        Efficient version: lists the repo root ONCE (1 API call), then only
        fetches content for files that are actually present. The naive
        approach (checking all 10 known filenames individually) burns 10
        requests per repo even when 0-1 of them exist — this cuts that to
        1 + (number actually found), which is what makes Phase 1 usable
        on the free 60/hr tier for more than a couple of repos.
        """
        try:
            resp = self._get(f"{GITHUB_API}/repos/{owner}/{repo}/contents/")
        except GitHubAPIError:
            return {}

        root_listing = resp.json()
        if not isinstance(root_listing, list):
            return {}

        root_filenames = {
            item["name"] for item in root_listing if item.get("type") == "file"
        }
        present = [fname for fname in DEPENDENCY_FILES if fname in root_filenames]

        found = {}
        for fname in present:
            content = self.get_file_content(owner, repo, fname)
            if content:
                found[fname] = content
        return found

    # ---------- orchestration ----------

    def fetch_full_profile(
        self,
        username: str,
        max_repos: int = 20,
        include_forks: bool = False,
        fetch_dependency_files: bool = True,
        progress_callback=None,
    ) -> dict:
        """
        Pulls everything Phase 2+ needs for one user:
          profile + repos, each with languages, README, and dependency files.

        progress_callback(str): optional, called with a status string per repo,
        handy for wiring up a Streamlit progress bar later.
        """
        profile = self.get_user_profile(username)
        raw_repos = self.get_user_repos(
            username, include_forks=include_forks, max_repos=max_repos
        )

        repo_data_list = []
        for r in raw_repos:
            name = r["name"]
            if progress_callback:
                progress_callback(f"Fetching {name}...")

            languages = self.get_repo_languages(username, name)
            readme = self.get_repo_readme(username, name)
            deps = (
                self.get_dependency_files(username, name)
                if fetch_dependency_files
                else {}
            )

            repo_data_list.append(
                RepoData(
                    name=name,
                    full_name=r["full_name"],
                    description=r.get("description"),
                    html_url=r["html_url"],
                    stargazers_count=r.get("stargazers_count", 0),
                    forks_count=r.get("forks_count", 0),
                    is_fork=r.get("fork", False),
                    is_archived=r.get("archived", False),
                    topics=r.get("topics", []),
                    languages=languages,
                    readme_text=readme,
                    dependency_files=deps,
                    pushed_at=r.get("pushed_at"),
                    created_at=r.get("created_at"),
                )
            )

        return {
            "profile": asdict(profile),
            "repos": [asdict(rd) for rd in repo_data_list],
        }


def save_profile_json(data: dict, out_path: str):
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        username = sys.argv[1]
    else:
        username = input("Enter the GitHub username to fetch: ").strip()
        if not username:
            print("No username entered. Exiting.")
            sys.exit(1)
    fetcher = GitHubFetcher()  # picks up GITHUB_TOKEN from .env automatically

    if fetcher.token:
        print("GITHUB_TOKEN loaded — using authenticated rate limit (5000/hr).")
    else:
        print("WARNING: No GITHUB_TOKEN found. Using unauthenticated limit (60/hr).")
        print("         Check that .env exists next to this script and contains")
        print("         GITHUB_TOKEN=ghp_... (no quotes, no spaces around '=').")

    try:
        status = fetcher.rate_limit_status()
        print(
            f"Rate limit: {status['remaining']}/{status['limit']} remaining "
            f"(resets at {time.strftime('%H:%M:%S', time.localtime(status['reset']))})"
        )
    except Exception:
        pass

    # Check how many public (non-fork) repos this user actually has, so we
    # don't silently truncate the fetch the way the old hardcoded max_repos=10
    # default used to. Optional 2nd CLI arg still overrides this explicitly:
    #   python github_fetcher.py <username> <max_repos>
    if len(sys.argv) > 2:
        max_repos = int(sys.argv[2])
    else:
        try:
            profile_peek = fetcher.get_user_profile(username)
            max_repos = max(profile_peek.public_repos, 1)
            print(
                f"'{username}' has {profile_peek.public_repos} public repos — "
                f"fetching up to all of them (pass a number as a 2nd argument to cap this)."
            )
        except Exception:
            max_repos = 30  # fallback if the profile peek itself fails

    print(f"\nFetching GitHub data for '{username}'...")
    result = fetcher.fetch_full_profile(
        username,
        max_repos=max_repos,
        progress_callback=lambda msg: print(f"  {msg}"),
    )

    out_file = f"{username}_github_data.json"
    save_profile_json(result, out_file)
    print(f"\nSaved {len(result['repos'])} repos to {out_file}")
    print(f"Profile: {result['profile']['name']} (@{result['profile']['username']})")
