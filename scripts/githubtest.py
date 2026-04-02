#!/usr/bin/env python3
"""
ghost_repos_v2.py - Verify BigQuery v2 results against the GitHub API.

Usage:
  1. Export BigQuery v2 results to CSV
  2. Run: python ghost_repos_v2.py bigquery_results.csv --token YOUR_GITHUB_TOKEN
  3. Output: ghost_repos_scored.csv

Requires: pip install httpx rich
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import sys
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path

import httpx
from rich.console import Console
from rich.table import Table
from rich.progress import track

console = Console()


@dataclass
class GhostRepo:
    repo_name: str
    push_events: int
    total_commits: int
    avg_commits_per_push: float
    distinct_pushers: int
    active_months: int
    stars_gained_2025: int
    # API-verified fields
    total_stars: int = 0
    total_forks: int = 0
    language: str = ""
    description: str = ""
    created_at: str = ""
    is_fork: bool = False
    is_archived: bool = False
    has_license: bool = False
    topics: list[str] = field(default_factory=list)
    html_url: str = ""
    # Computed
    ghost_score: float = 0.0

    def compute_ghost_score(self) -> None:
        """push_events / log10(total_stars + 2). Higher = more invisible dedication."""
        if self.total_stars == 0:
            self.ghost_score = float(self.push_events)
        else:
            self.ghost_score = round(
                self.push_events / math.log10(self.total_stars + 2), 1
            )


def load_bigquery_csv(path: Path) -> list[GhostRepo]:
    repos = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            repos.append(GhostRepo(
                repo_name=row["repo_name"],
                push_events=int(row.get("push_events", 0)),
                total_commits=int(row.get("total_commits", 0)),
                avg_commits_per_push=float(row.get("avg_commits_per_push", 0)),
                distinct_pushers=int(row.get("distinct_pushers", 0)),
                active_months=int(row.get("active_months", 0)),
                stars_gained_2025=int(row.get("stars_gained_2025", 0)),
            ))
    return repos


def verify_repo(client: httpx.Client, repo: GhostRepo) -> bool:
    """Fetch true metadata from GitHub API. Returns False if repo is gone."""
    try:
        resp = client.get(f"https://api.github.com/repos/{repo.repo_name}")

        if resp.status_code == 404:
            return False

        if resp.status_code in (403, 429):
            body = resp.text
            console.print(f"[red]403/429 body: {body[:200]}[/red]")
        
            # TOS-blocked or DMCA'd repo — skip it, not a rate limit
            if "access blocked" in body or "Repository unavailable" in body:
                console.print(f"[yellow]Repo blocked (TOS/DMCA), skipping[/yellow]")
                return False
        
            # Actual rate limit — wait and retry
            retry_after = resp.headers.get("retry-after")
            if retry_after:
                wait = int(retry_after) + 2
            else:
                reset = int(resp.headers.get("x-ratelimit-reset", 0))
                wait = max(reset - int(time.time()), 60)
            console.print(f"[yellow]Rate limited. Waiting {wait}s...[/yellow]")
            time.sleep(wait)
            return verify_repo(client, repo)

        resp.raise_for_status()
        data = resp.json()

        repo.total_stars = data.get("stargazers_count", 0)
        repo.total_forks = data.get("forks_count", 0)
        repo.language = data.get("language") or ""
        repo.description = (data.get("description") or "")[:200]
        repo.created_at = (data.get("created_at") or "")[:10]
        repo.is_fork = data.get("fork", False)
        repo.is_archived = data.get("archived", False)
        repo.has_license = data.get("license") is not None
        repo.topics = data.get("topics", [])
        repo.html_url = data.get("html_url", "")
        repo.compute_ghost_score()
        return True

    except httpx.HTTPError as e:
        console.print(f"[red]Error fetching {repo.repo_name}: {e}[/red]")
        return False


def filter_noise(repo: GhostRepo) -> tuple[bool, str]:
    if repo.is_fork:
        return False, "fork"
    if repo.is_archived:
        return False, "archived"
    if repo.total_stars > 15:
        return False, f"too many stars ({repo.total_stars})"

    name_lower = repo.repo_name.lower()
    owner = repo.repo_name.split("/")[0]
    name = repo.repo_name.split("/")[1] if "/" in repo.repo_name else ""

    if name == owner:
        return False, "profile repo"

    noise_patterns = [
        "mirror", "backup", "dotfiles", "upptime", "statuspage",
        ".github.io", "homebrew-", "ansible-role", "terraform-",
        "nixpkgs", "gentoo", "kernel", "slackbuilds",
    ]
    for pattern in noise_patterns:
        if pattern in name_lower:
            return False, f"noise: {pattern}"

    return True, ""


def print_results(repos: list[GhostRepo], top_n: int = 40) -> None:
    table = Table(
        title=f"?? Top {min(top_n, len(repos))} Ghost Repos",
        show_lines=True,
    )
    table.add_column("#", style="dim", width=3)
    table.add_column("Repository", style="bold cyan", max_width=42)
    table.add_column("Pushes", justify="right", style="green")
    table.add_column("Commits", justify="right", style="green dim")
    table.add_column("?", justify="right", style="yellow")
    table.add_column("Ghost", justify="right", style="magenta bold")
    table.add_column("Lang", width=12)
    table.add_column("Team", justify="right", width=4)
    table.add_column("Months", justify="right", width=6)
    table.add_column("Since", width=10)
    table.add_column("Description", max_width=45)

    for i, repo in enumerate(repos[:top_n], 1):
        table.add_row(
            str(i),
            repo.repo_name,
            f"{repo.push_events:,}",
            f"{repo.total_commits:,}",
            str(repo.total_stars),
            f"{repo.ghost_score:,.0f}",
            repo.language or "-",
            str(repo.distinct_pushers),
            str(repo.active_months),
            repo.created_at,
            (repo.description[:42] + "...") if len(repo.description) > 42 else repo.description,
        )

    console.print(table)


def save_results(repos: list[GhostRepo], path: Path) -> None:
    fields = [
        "repo_name", "push_events", "total_commits", "total_stars",
        "ghost_score", "language", "description", "created_at",
        "distinct_pushers", "active_months", "is_fork", "has_license",
        "html_url", "topics",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for repo in repos:
            d = asdict(repo)
            d["topics"] = "; ".join(d["topics"])
            writer.writerow({k: d[k] for k in fields})
    console.print(f"\n[green]Saved {len(repos)} repos to {path}[/green]")


def check_ratelimit(client):
    console.print("checking rate limits and headers")
    present = 'pat' in client.headers.get("Authorization", "")
    if present:
        console.print("token still in headers")
    else:
        console.print("it seems we have lost the token")
        console.print(client.headers)
        sys.exit(1)
    ratecheck = client.get("https://api.github.com/rate_limit")
    if limit := ratecheck.json().get("rate", {}).get("limit"):
        if limit < 5000:
            console.print("[red] Apparently we're not authenticated...[/red]")
            console.print(f"response: {ratecheck.json()}")
        else:
            console.print("[green] authenticated -- let's continue [/green]")
    else:
        console.print(f"[yellow] hmm, we don't have the rate key, keys: {ratecheck.json().keys()}")

def main() -> None:
    parser = argparse.ArgumentParser(description="Ghost Repos v2 - verify and score")
    parser.add_argument("csv_path", type=Path, help="BigQuery CSV export")
    parser.add_argument("--token", "-t", type=str, help="GitHub personal access token")
    parser.add_argument("--max-stars", type=int, default=15,
                        help="Max total stars to keep (default: 15)")
    parser.add_argument("--top", type=int, default=50)
    parser.add_argument("--output", "-o", type=Path,
                        default=Path("ghost_repos_v2_scored.csv"))
    args = parser.parse_args()

    repos = load_bigquery_csv(args.csv_path)
    console.print(f"Loaded {len(repos)} repos from BigQuery export")

    headers = {"Accept": "application/vnd.github.v3+json"}
    token = args.token or os.environ.get("MISE_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
        console.print("[green]Authenticated (5,000 req/hr)[/green]")
    else:
        console.print("[yellow]No token - 60 req/hr. Use --token![/yellow]")

    verified = []
    skipped: dict[str, int] = {}

    with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
        check_ratelimit(client)
        for repo in track(repos, description="Verifying..."):
            if not verify_repo(client, repo):
                skipped["404/error"] = skipped.get("404/error", 0) + 1
                continue

            keep, reason = filter_noise(repo)
            if not keep:
                skipped[reason] = skipped.get(reason, 0) + 1
                continue

            verified.append(repo)
            time.sleep(2.0)

    verified.sort(key=lambda r: r.ghost_score, reverse=True)

    console.print(f"\n[bold]{len(verified)} ghost repos verified[/bold]")
    if skipped:
        console.print("[dim]Filtered:[/dim]")
        for reason, count in sorted(skipped.items(), key=lambda x: -x[1]):
            console.print(f"  {reason}: {count}")

    print_results(verified, top_n=args.top)
    save_results(verified, args.output)


if __name__ == "__main__":
    main()
