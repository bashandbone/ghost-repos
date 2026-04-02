# SQL Query Iterations

The BigQuery queries that produced the raw data went through six iterations (v1–v5, then v6.1). The SQL files for all versions are in this folder. v1 was a dead end abandoned immediately, documented below for completeness.

**v6.1 is the final query** — the one that produced `data/processed/ghost_repos_v5_final.csv`, the dataset used in the blog post and data explorer. (The output file kept its v5 name from when the pipeline was first set up; the query that generated it is v6.1.)

v5 was a direct precursor — same structure and thresholds, but limited to 2025 data and with slightly looser filters. v6.1 extended the date range, raised the activity bar, and added more noise patterns.

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

## v5 — Meaningful workflow thresholds + two-stage GitHub API check

**What it did:**
- Required 5+ issue events, 5+ PR events, and 20+ combined workflow events
- Required at least 6 active months and 1–5 human pushers
- Push events capped at 100–3500
- Called the GitHub API for each candidate in two stages:
  - **Stage 1**: Basic validation (star count, fork status, language, whether it's archived)
  - **Stage 2**: Quality inspection (README presence and length, test files, CI config, release count, commit message diversity)
- Filtered out known noise patterns: mirrors, backups, dotfiles, status pages, uptime monitors

**Limitation:** Date range was 2025 only. A few noise patterns (tutorial repos, templates, course assignments) still slipped through.

SQL: [`v05_codeweaver_profile.sql`](v05_codeweaver_profile.sql)

---

## v6.1 — The final query: extended date range + tighter noise filters

**What it did:**
- **UNION ALL** across `githubarchive.month.2025*` and `githubarchive.month.2026*` to cover the full data window (BigQuery requires UNION ALL to query multiple wildcard table prefixes)
- Raised `active_months` threshold from 6 to **8** — stricter consistency requirement
- Widened `push_events` range to **150–5000** (catches active projects at the lower end that v5 missed)
- Added noise filter patterns: `template`, `tutorial`, `learn-`, `awesome-`, `practice`, `course`, `assignment`, `homework`
- Renamed output columns `stars_period` / `forks_period` to reflect the multi-year date range

**Result:** This is the query that produced the 401-repo dataset — `ghost_repos_v5_final.csv`. The file kept its v5 name from when the pipeline was originally set up.

SQL: [`v06.1_codeweaver_expansion.sql`](v06.1_codeweaver_expansion.sql)

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
| `bquxjob_6df66b77_19d449db63d.csv` | v5 input | 99 | Full 2025 |
| `bquxjob_412f814a_19d44cadf87.csv` | v6.1 input → scored into `ghost_repos_v5_final.csv` | 999 | 2025-01-01 to 2026-03-30 |

---

## Re-running the pipeline

See the main [README](../README.md#how-to-re-run-the-pipeline) for instructions on running a new BigQuery query and processing the output through the scoring pipeline.
