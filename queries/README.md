# SQL Query Iterations

The BigQuery queries that produced the raw data went through five iterations (v1–v5). The SQL files for v2–v5 are in this folder. v1 was a dead end abandoned immediately, documented below for completeness.

**v5 is the final query** — the one that produced `data/processed/ghost_repos_v5_final.csv`, the dataset used in the blog post and data explorer.

The source data is the [`githubarchive`](https://www.gharchive.org/) public dataset in BigQuery. We queried roughly 5 TB of event data spanning all of 2025 and early 2026.

---

## v1 — Commit count from push events

**What it did:** Summed the commit count field from push events.

**Problem:** BigQuery records every push event, including "push all refs" events when a repo is first forked or cloned. A single clone can appear as 100,000+ "commits." The top results were nonsense. This approach was abandoned immediately without saving the SQL.

---

## v2 — Count push events instead

**What it did:** Counted push events (not commit fields). Required at least 4 months of activity. Returned the top 500 repos by push event count.

**Problem:** The top 500 were almost entirely automated repos — CI bots, uptime monitors, dependency updaters. Still very noisy.

SQL: [`v02_push_events.sql`](v02_push_events.sql)

---

## v3 — Add an upper bound on push frequency

**What it did:** Added a cap on total push events to filter out the most extreme bot behavior. Also added a filter for distinct pushers (≤ 5) and began sorting by consistency (active months) rather than raw volume.

**Problem:** Uptime monitors, scraper repos, and status page generators all stayed under the cap. The name-based filters (excluding repos with "upptime", "mirror", "status" in the name) helped somewhat but were too easy to bypass — a legitimate project could have any of those words in its name, and a bot repo might not.

SQL: [`v03_human_scale.sql`](v03_human_scale.sql)

---

## v4 — Require PR and issue activity

**What it did:** Required some minimum number of pull requests and issues to filter out pure automation (bots don't usually file issues or review PRs). Switched to a single-pass scan of the table (one CTE reading all event types) rather than multiple CTEs hitting the same data repeatedly — much cheaper on BigQuery.

**Problem:** Renovate and Dependabot create PRs. A lot of bot-heavy repos still made it through. The PR/issue threshold needed to be much higher.

SQL: [`v04_soul_poured.sql`](v04_soul_poured.sql)

---

## v5 — The final query: meaningful workflow thresholds + two-stage GitHub API check

**What it did:**
- Required 5+ issue events, 5+ PR events, and 20+ combined workflow events
- Required at least 6 active months and 1–5 human pushers
- Called the GitHub API for each candidate in two stages:
  - **Stage 1**: Basic validation (star count, fork status, language, whether it's archived)
  - **Stage 2**: Quality inspection (README presence and length, test files, CI config, release count, commit message diversity)
- Filtered out known noise patterns: mirrors, backups, dotfiles, status pages, uptime monitors

**Result:** `ghost_repos_v5_final.csv` — 401 repos, the dataset used in the blog post.

SQL: [`v05_codeweaver_profile.sql`](v05_codeweaver_profile.sql)

---

## What didn't make it: lessons on noise filtering

The main lesson across these iterations: **name-based filters are a weak signal.**

Filtering by repo name patterns like `*mirror*`, `*upptime*`, `*status*` catches obvious cases but misses sophisticated automation and occasionally hits legitimate projects. The better signal turned out to be activity structure — specifically the mix of issue events, PR events, and push events. Bots push; humans file issues, review PRs, and leave comments.

If you're running this pipeline again and want to improve noise filtering, the right direction is:
- Require higher minimum thresholds on issue and PR activity (not just non-zero)
- Look at the ratio of issue/PR events to push events — humans use issues as part of their workflow even on solo projects
- Use the GitHub API quality signals (test presence, CI config) as post-filters rather than trying to guess from repo names

The scoring pipeline in `scripts/main.py` already does this to some extent with its two-stage verification — the name-based filters in the SQL query are a rough first pass, and the API checks are where the real quality signal comes in.

---

## What the raw CSVs contain

| File | Query version | Rows | Date range |
|------|--------------|------|------------|
| `bq-results-20260327-032336-1774582099303.csv` | Early v2/v3 run | 500 | 2025-01-01 to 2025-08-13 |
| `bquxjob_6df66b77_19d449db63d.csv` | v5 input (small batch) | 99 | Full 2025 |
| `bquxjob_412f814a_19d44cadf87.csv` | v5 extended date run | 999 | 2025-01-01 to 2026-03-30 |

The 999-row file (`bquxjob_412f814a`) was produced by running the v5 query structure against an extended date range (through March 2026). It hasn't been fully scored through the Python pipeline yet — it's there for future runs.

---

## Re-running the pipeline

See the main [README](../README.md#how-to-re-run-the-pipeline) for instructions on running a new BigQuery query and processing the output through the scoring pipeline.
