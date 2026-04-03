#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx", "rich"]
# ///
# sourcery skip: avoid-global-variables
"""
ghost_repos_v5.py — Two-stage verification for Ghost Repos.

Stage 1: Basic API check (stars, fork status, language, description)
Stage 2: Quality inspection (releases, commit message diversity,
         README presence, test signals, contributor commit patterns)

Usage:
  python ghost_repos_v5.py bigquery_export.csv --token $GITHUB_TOKEN

Requires: pip install httpx rich
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import math
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import httpx
from rich.console import Console
from rich.progress import track
from rich.table import Table

console = Console(markup=True)

# Languages that indicate real code (not data, config, or docs)
CODE_LANGUAGES = frozenset({
    "ada",
    "assembly",
    "c",
    "c#",
    "c++",
    "clojure",
    "common lisp",
    "crystal",
    "d",
    "dart",
    "elixir",
    "erlang",
    "f#",
    "fortran",
    "gleam",
    "go",
    "haskell",
    "java",
    "javascript",
    "julia",
    "kotlin",
    "lua",
    "nim",
    "objective-c",
    "ocaml",
    "odin",
    "perl",
    "php",
    "powershell",
    "python",
    "r",
    "racket",
    "ruby",
    "rust",
    "scala",
    "scheme",
    "swift",
    "typescript",
    "v",
    "visual basic .net",
    "zig",
})


@dataclass
class GhostRepo:
    repo_name: str
    push_events: int
    total_commits: int
    active_months: int
    active_weeks: int
    stars_gained_2025: int
    issues_opened: int
    issue_comments: int
    pr_events: int
    pr_reviews: int
    project_activity_score: int
    releases: int
    tags_created: int
    branches_created: int
    human_pushers: int

    # Stage 1: API basics
    total_stars: int = 0
    total_forks: int = 0
    language: str = ""
    description: str = ""
    created_at: str = ""
    is_fork: bool = False
    is_archived: bool = False
    license: str = ""
    topics: list[str] = field(default_factory=list)
    html_url: str = ""
    default_branch: str = "main"

    # Stage 2: Quality signals
    languages_breakdown: dict = field(default_factory=dict)
    has_readme: bool = False
    readme_length: int = 0
    has_tests: bool = False
    has_ci: bool = False
    has_docs: bool = False
    release_count_api: int = 0
    recent_commit_messages: list[str] = field(default_factory=list)
    commit_message_diversity: float = 0.0
    repo_age_days: int = 0

    # Computed scores
    ghost_score: float = 0.0
    quality_score: float = 0.0
    combined_score: float = 0.0

    def compute_scores(self) -> None:
        """Compute ghost_score, quality_score, and combined_score based on signals."""
        # Ghost score: push activity relative to visibility
        if self.total_stars == 0:
            self.ghost_score = float(self.push_events)
        else:
            self.ghost_score = round(
                self.push_events / math.log10(self.total_stars + 2), 1
            )

        # Quality score: composite of project health signals
        q = 0.0
        q += min(self.project_activity_score / 100, 3.0)  # PR/issue activity, cap at 3
        q += 1.0 if self.has_readme else 0.0
        q += min(self.readme_length / 2000, 1.0)  # Longer README = more effort
        q += 1.0 if self.has_tests else 0.0
        q += 1.0 if self.has_ci else 0.0
        q += 1.0 if self.license else 0.0
        q += min(self.release_count_api / 5, 1.0)  # Has releases
        q += min(self.commit_message_diversity, 1.0)  # Diverse commit messages
        q += min(len(self.languages_breakdown) / 3, 1.0)  # Multiple languages
        q += min(self.active_weeks / 30, 1.0)  # Consistency
        self.quality_score = round(q, 2)

        # Combined: quality * invisibility
        if self.total_stars <= 1:
            invisibility = 5.0
        else:
            invisibility = 1.0 / math.log10(self.total_stars + 1)
        self.combined_score = round(self.quality_score * invisibility * 100, 1)


def load_bigquery_csv(path: Path) -> list[GhostRepo]:
    """Load repos from BigQuery CSV export."""
    repos = []
    with open(path) as f:
        reader = csv.DictReader(f)
        repos.extend(
            GhostRepo(
                repo_name=row["repo_name"],
                push_events=int(row.get("push_events", 0)),
                total_commits=int(row.get("total_commits", 0)),
                active_months=int(row.get("active_months", 0)),
                active_weeks=int(row.get("active_weeks", 0)),
                stars_gained_2025=int(
                    row.get("stars_2025", row.get("stars_gained_2025", 0))
                ),
                issues_opened=int(row.get("issues_opened", 0)),
                issue_comments=int(row.get("issue_comments", 0)),
                pr_events=int(row.get("pr_events", 0)),
                pr_reviews=int(row.get("pr_reviews", 0)),
                project_activity_score=int(row.get("project_activity_score", 0)),
                releases=int(row.get("releases", 0)),
                tags_created=int(row.get("tags_created", 0)),
                branches_created=int(row.get("branches_created", 0)),
                human_pushers=int(row.get("human_pushers", 0)),
            )
            for row in reader
        )
    return repos


def api_get(client: httpx.Client, url: str) -> dict | list | None:
    """Make a GitHub API request with rate limit handling."""
    try:
        resp = client.get(url)
        if resp.status_code == 404:
            return None
        if (
            resp.status_code in (403, 429)
            and (body := resp.text)
            and ("access blocked" in body or "Repository unavailable" in body)
        ):
            retry_after = resp.headers.get("retry-after")
            wait = int(retry_after) + 2 if retry_after else 65
            console.print(f"[yellow]Rate limited, waiting {wait}s...[/yellow]")
            time.sleep(wait)
            return api_get(client, url)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        console.print(f"[red]HTTP error: {e}[/red]")
        return None


def stage1_verify(client: httpx.Client, repo: GhostRepo) -> bool:
    """Basic API verification. Returns False if repo should be skipped."""
    data = api_get(client, f"https://api.github.com/repos/{repo.repo_name}")
    if data is None or not isinstance(data, dict):
        return False

    repo.total_stars = data.get("stargazers_count", 0)
    repo.total_forks = data.get("forks_count", 0)
    repo.language = data.get("language") or ""
    repo.description = (data.get("description") or "")[:200]
    repo.created_at = (data.get("created_at") or "")[:10]
    repo.is_fork = data.get("fork", False)
    repo.is_archived = data.get("archived", False)
    repo.license = (data.get("license") or {}).get("spdx_id", "")
    repo.topics = data.get("topics", [])
    repo.html_url = data.get("html_url", "")
    repo.default_branch = data.get("default_branch", "main")

    # Calculate age
    if repo.created_at:
        with contextlib.suppress(ValueError):
            created = datetime.fromisoformat(repo.created_at)
            repo.repo_age_days = (datetime.now() - created).days
    # Filter: must be real code language, not a fork, not archived
    if repo.is_fork:
        return False
    if repo.is_archived:
        return False
    if repo.total_stars > 50:
        return False
    if repo.language and repo.language.lower() not in CODE_LANGUAGES:
        # Still allow if no detected language (might be multi-language)
        # We'll check in stage 2
        pass

    time.sleep(1.5)
    return True


def stage2_inspect(client: httpx.Client, repo: GhostRepo) -> None:
    """Deep quality inspection."""

    if isinstance(
        langs := api_get(
            client, f"https://api.github.com/repos/{repo.repo_name}/languages"
        ),
        dict,
    ):
        repo.languages_breakdown = langs
    time.sleep(1.0)

    # Check if any language is a real code language
    if repo.languages_breakdown:
        has_code = any(
            lang.lower() in CODE_LANGUAGES for lang in repo.languages_breakdown
        )
        if not has_code:
            return  # No real code, don't bother with more API calls

    # 2. Check repo contents for README, tests, CI, docs
    contents = api_get(
        client, f"https://api.github.com/repos/{repo.repo_name}/contents"
    )
    if contents and isinstance(contents, list):
        _extract_repo_file_info(contents, repo)
    time.sleep(1.0)

    # 3. Releases
    releases = api_get(
        client, f"https://api.github.com/repos/{repo.repo_name}/releases?per_page=5"
    )
    if releases and isinstance(releases, list):
        repo.release_count_api = len(releases)
    time.sleep(1.0)

    # 4. Recent commit messages (diversity check)
    commits = api_get(
        client, f"https://api.github.com/repos/{repo.repo_name}/commits?per_page=30"
    )
    if commits and isinstance(commits, list):
        messages = []
        for c in commits:
            if (
                msg := (c.get("commit", {}).get("message", "") or "")
                .split("\n")[0]
                .strip()
            ):
                messages.append(msg)
        repo.recent_commit_messages = messages[:30]

        # Compute diversity: ratio of unique first-words to total messages
        # "Update data" x30 = low diversity. Varied messages = high diversity.
        if messages:
            first_words = [m.split()[0].lower() if m.split() else "" for m in messages]
            unique_ratio = len(set(first_words)) / len(first_words)
            # Also check for repetitive exact messages
            unique_msg_ratio = len(set(messages)) / len(messages)
            repo.commit_message_diversity = round(
                (unique_ratio + unique_msg_ratio) / 2, 3
            )
    time.sleep(1.0)

    repo.compute_scores()


def _extract_repo_file_info(contents, repo):
    """Extract file information from the repository contents."""
    names = [item.get("name", "").lower() for item in contents]
    repo.has_readme = any(n.startswith("readme") for n in names)
    repo.has_tests = any(
        n
        in (
            "tests",
            "test",
            "__tests__",
            "spec",
            "specs",
            "test.py",
            "tests.py",
            "pytest.ini",
            "jest.config.js",
            "vitest.config.ts",
        )
        for n in names
    )
    repo.has_ci = any(
        n
        in (
            ".github",
            ".gitlab-ci.yml",
            ".circleci",
            ".travis.yml",
            "jenkinsfile",
            ".drone.yml",
        )
        for n in names
    )
    repo.has_docs = any(
        n in ("docs", "doc", "documentation", "wiki", "guide") for n in names
    )

    # Get README size if present
    for item in contents:
        if item.get("name", "").lower().startswith("readme"):
            repo.readme_length = item.get("size", 0)
            break


def print_results(repos: list[GhostRepo], top_n: int = 50) -> None:
    """Print results in a rich table."""
    table = Table(title=f"👻 Top {min(top_n, len(repos))} Ghost Repos", show_lines=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("Repository", style="bold cyan", max_width=40)
    table.add_column("⭐", justify="right", style="yellow", width=4)
    table.add_column("Age", justify="right", width=5)
    table.add_column("Push", justify="right", style="green", width=5)
    table.add_column("PRs", justify="right", width=4)
    table.add_column("Issues", justify="right", width=5)
    table.add_column("Qual", justify="right", style="magenta", width=5)
    table.add_column("Score", justify="right", style="magenta bold", width=6)
    table.add_column("Lang", width=11)
    table.add_column("Lic", width=8)
    table.add_column("Signals", max_width=20)
    table.add_column("Description", max_width=40)

    for i, repo in enumerate(repos[:top_n], 1):
        signals = []
        if repo.has_readme:
            signals.append("📄")
        if repo.has_tests:
            signals.append("🧪")
        if repo.has_ci:
            signals.append("⚙️")
        if repo.has_docs:
            signals.append("📚")
        if repo.release_count_api > 0:
            signals.append(f"🏷️×{repo.release_count_api}")

        formatted_repo_age = (
            f"{repo.repo_age_days // 365}y"
            if repo.repo_age_days >= 365
            else f"{repo.repo_age_days // 30}mo"
        )

        table.add_row(
            str(i),
            repo.repo_name,
            str(repo.total_stars),
            formatted_repo_age,
            str(repo.push_events),
            str(repo.pr_events),
            str(repo.issues_opened),
            f"{repo.quality_score:.1f}",
            f"{repo.combined_score:.0f}",
            repo.language or "—",
            repo.license[:8] if repo.license else "—",
            " ".join(signals),
            (
                f"{repo.description[:37]}..."
                if len(repo.description) > 37
                else repo.description
            ),
        )
    console.print(table)


def save_results(repos: list[GhostRepo], path: Path) -> None:
    """Save results to CSV."""
    fields = [
        "repo_name",
        "total_stars",
        "repo_age_days",
        "push_events",
        "total_commits",
        "active_months",
        "active_weeks",
        "pr_events",
        "pr_reviews",
        "issues_opened",
        "issue_comments",
        "project_activity_score",
        "releases",
        "tags_created",
        "human_pushers",
        "language",
        "license",
        "description",
        "created_at",
        "is_fork",
        "has_readme",
        "readme_length",
        "has_tests",
        "has_ci",
        "has_docs",
        "release_count_api",
        "commit_message_diversity",
        "quality_score",
        "ghost_score",
        "combined_score",
        "html_url",
        "topics",
        "languages_breakdown",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for repo in repos:
            d = asdict(repo)
            d["topics"] = "; ".join(d["topics"])
            d["languages_breakdown"] = "; ".join(
                f"{k}:{v}" for k, v in d["languages_breakdown"].items()
            )
            writer.writerow({k: d.get(k, "") for k in fields})
    console.print(f"\n[green]Saved {len(repos)} repos to {path}[/green]")


def main() -> None:
    """Main function to run the two-stage verification process."""
    parser = argparse.ArgumentParser(description="Ghost Repos v5 — two-stage verify")
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--token", "-t", type=str)
    parser.add_argument("--max-stars", type=int, default=50)
    parser.add_argument("--top", type=int, default=50)
    parser.add_argument(
        "--output", "-o", type=Path, default=Path("ghost_repos_v5_final.csv")
    )
    parser.add_argument("--skip-stage2", action="store_true", help="Only run stage 1")
    args = parser.parse_args()

    repos = load_bigquery_csv(args.csv_path)
    console.print(f"Loaded {len(repos)} candidate repos")

    headers = {"Accept": "application/vnd.github.v3+json"}
    token = (
        args.token
        or os.environ.get("MISE_GITHUB_TOKEN")
        or os.environ.get("GITHUB_TOKEN")
    )
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        console.print(
            "[red]No token — this will be very slow. Use --token or set GITHUB_TOKEN.[/red]"
        )
        sys.exit(1)

    # Rate limit check
    with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
        if (rl := api_get(client, "https://api.github.com/rate_limit")) and isinstance(
            rl, dict
        ):
            limit = rl.get("rate", {}).get("limit", 0)
            remaining = rl.get("rate", {}).get("remaining", 0)
            console.print(f"Rate limit: {remaining}/{limit}")
            if limit < 5000:
                console.print("[red]Not authenticated![/red]")
                sys.exit(1)

    # Stage 1: Basic verification
    console.print("\n[bold]Stage 1: Basic verification[/bold]")
    stage1_passed = []
    stage1_skipped: dict[str, int] = {}

    with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
        for repo in track(repos, description="Stage 1..."):
            if not stage1_verify(client, repo):
                reason = (
                    "fork"
                    if repo.is_fork
                    else "archived"
                    if repo.is_archived
                    else "filtered"
                )
                if repo.total_stars > args.max_stars:
                    reason = f"stars={repo.total_stars}"
                stage1_skipped[reason] = stage1_skipped.get(reason, 0) + 1
                continue

            # Check for real code language
            if repo.language and repo.language.lower() not in CODE_LANGUAGES:
                stage1_skipped[f"lang:{repo.language}"] = (
                    stage1_skipped.get(f"lang:{repo.language}", 0) + 1
                )
                continue

            stage1_passed.append(repo)

    console.print(
        f"Stage 1: {len(stage1_passed)} passed, {sum(stage1_skipped.values())} skipped"
    )
    for reason, count in sorted(stage1_skipped.items(), key=lambda x: -x[1]):
        console.print(f"  [dim]{reason}: {count}[/dim]")

    if args.skip_stage2:
        for r in stage1_passed:
            r.compute_scores()
        stage1_passed.sort(key=lambda r: r.combined_score, reverse=True)
        print_results(stage1_passed, top_n=args.top)
        save_results(stage1_passed, args.output)
        return

    # Stage 2: Deep quality inspection
    console.print(
        f"\n[bold]Stage 2: Quality inspection ({len(stage1_passed)} repos)[/bold]"
    )
    console.print(
        f"[dim]~5 API calls per repo, ~{len(stage1_passed) * 5 * 1.5 / 60:.0f} minutes[/dim]"
    )

    final = []
    with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
        for repo in track(stage1_passed, description="Stage 2..."):
            stage2_inspect(client, repo)

            # Post-stage2 filter: must have at least SOME code language
            if repo.languages_breakdown:
                has_code = any(
                    lang.lower() in CODE_LANGUAGES for lang in repo.languages_breakdown
                )
                if not has_code:
                    continue

            # Must have non-trivial commit message diversity
            # (filters out "Update data" x1000 bots that slipped through)
            if repo.commit_message_diversity < 0.3:
                continue

            final.append(repo)

    final.sort(key=lambda r: r.combined_score, reverse=True)

    console.print(f"\n[bold green]{len(final)} ghost repos found[/bold green]")
    print_results(final, top_n=args.top)
    save_results(final, args.output)

    # Print some fun stats
    if final:
        _display_combined_metrics(final)


def _display_combined_metrics(final):
    """Display combined metrics for the final ghost repos."""
    total_commits = sum(r.total_commits for r in final)
    total_stars = sum(r.total_stars for r in final)
    avg_age = sum(r.repo_age_days for r in final) / len(final)
    console.print(
        f"\n[dim]Combined: {total_commits:,} commits across {len(final)} repos"
    )
    console.print(f"Total stars across all repos: {total_stars}")
    console.print(f"Average repo age: {avg_age / 365:.1f} years")
    console.print(
        f"That's {total_commits / max(total_stars, 1):,.0f} commits per star.[/dim]"
    )


if __name__ == "__main__":
    main()
