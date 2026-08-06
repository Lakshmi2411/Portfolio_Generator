"""
Orchestrator: runs Phase 1 through Phase 5 end-to-end for one GitHub username,
computing every intermediate file path itself instead of prompting for it.

This is the piece Phase 6 (the Streamlit app) wraps a UI around — the app
should never need to ask "what's the path to your Phase 3 JSON file?", it
should just call run_pipeline(username) and get a finished portfolio back.

What this does NOT remove: the genuine human-in-the-loop decision points
inside Phase 2 (which roles, which repos, confirm gap-fill additions, add
work experience). Those are real choices the person needs to make, not file
plumbing — Phase 6 will surface them as proper UI controls rather than
terminal input() prompts, but the underlying phase2 module still expects
input() for now since it's still usable standalone from the CLI.
"""

import os
import sys
from typing import Optional

from github_fetcher import GitHubFetcher, save_profile_json, GitHubAPIError
from role_selection import run_phase2
from technical_scan import run_phase3
from content_generation import run_phase4
from portfolio_template import run_phase5
from llm_client import LLMError


class PipelinePaths:
    """All intermediate file paths for one run, derived from username + output dir."""

    def __init__(self, username: str, output_dir: str = "."):
        os.makedirs(output_dir, exist_ok=True)
        self.phase1 = os.path.join(output_dir, f"{username}_phase1_github.json")
        self.phase2 = os.path.join(output_dir, f"{username}_phase2_roles.json")
        self.phase3 = os.path.join(output_dir, f"{username}_phase3_techscan.json")
        self.phase4 = os.path.join(output_dir, f"{username}_phase4_content.json")
        self.portfolio = os.path.join(output_dir, f"{username}_portfolio.html")


def run_phase1(
    username: str,
    output_path: str,
    max_repos: Optional[int] = None,
    progress_callback=None,
) -> dict:
    """Thin wrapper matching the run_phaseN(...) shape the other phases use."""
    fetcher = GitHubFetcher()

    if max_repos is None:
        profile = fetcher.get_user_profile(username)
        max_repos = max(profile.public_repos, 1)

    result = fetcher.fetch_full_profile(
        username, max_repos=max_repos, progress_callback=progress_callback
    )
    save_profile_json(result, output_path)
    return result


def run_pipeline(
    username: str,
    output_dir: str = ".",
    max_repos: Optional[int] = None,
    progress_callback=None,
) -> str:
    """
    Runs Phase 1-5 for `username`, returns the path to the finished portfolio.html.
    progress_callback(str), if given, is called with a status line at the start
    of each phase — useful for wiring up a Streamlit progress indicator later.
    """
    paths = PipelinePaths(username, output_dir)

    def notify(msg):
        print(msg)
        if progress_callback:
            progress_callback(msg)

    notify(f"Phase 1: fetching GitHub data for '{username}'...")
    run_phase1(
        username,
        paths.phase1,
        max_repos=max_repos,
        progress_callback=lambda m: notify(f"  {m}"),
    )

    notify("\nPhase 2: role targeting, repo selection, gap analysis...")
    run_phase2(paths.phase1, output_path=paths.phase2)

    notify("\nPhase 3: technical deep scan...")
    run_phase3(paths.phase1, paths.phase2, output_path=paths.phase3)

    notify("\nPhase 4: generating content...")
    run_phase4(paths.phase1, paths.phase2, paths.phase3, output_path=paths.phase4)

    notify("\nPhase 5: rendering portfolio...")
    run_phase5(
        paths.phase1,
        paths.phase2,
        paths.phase3,
        paths.phase4,
        output_path=paths.portfolio,
    )

    notify(f"\nDone. Portfolio saved to {paths.portfolio}")
    return paths.portfolio


if __name__ == "__main__":
    username = sys.argv[1] if len(sys.argv) > 1 else input("GitHub username: ").strip()
    try:
        run_pipeline(username)
    except (GitHubAPIError, LLMError) as e:
        print(f"\nPipeline failed: {e}")
        sys.exit(1)
