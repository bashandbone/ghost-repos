# SQL Query Iterations

The BigQuery queries that produced the raw data went through six iterations. The SQL wasn't saved as files — it was written interactively — but here's what each version did and why it changed.

The source data is the [`githubarchive`](https://www.gharchive.org/) public dataset in BigQuery. We queried roughly 5 TB of event data spanning all of 2025 and early 2026.

---

## v1 — Commit count from push events

**What it did:** Summed the commit count field from push events.

**Problem:** BigQuery records every push event, including "push all refs" events when a repo is first forked or cloned. A single clone can appear as 100,000+ "commits." The top results were nonsense.

---

## v2 — Count push events instead

**What it did:** Counted push events (not commit fields). Required at least 8 months of activity. Returned the top 500 repos by push event count.

**Problem:** The top 500 were almost entirely automated repos — CI bots, uptime monitors, dependency updaters. Still very noisy.

---

## v3 — Add an upper bound on push frequency

**What it did:** Added a cap on total push events to filter out the most extreme bot behavior. Also added a filter for distinct pushers (≤ 3).

**Problem:** Uptime monitors, scraper repos, and status page generators all stayed under the cap. Still mostly noise.

---

## v4 — Require PR and issue activity

**What it did:** Required some minimum number of pull requests and issues to filter out pure automation (bots don't usually file issues or review PRs).

**Problem:** Renovate and Dependabot create PRs. A lot of bot-heavy repos still made it through. Some genuinely human repos were caught by overly strict thresholds.

---

## v5 — Meaningful activity thresholds + two-stage GitHub API check

**What it did:**
- Required 10+ PR events, 5+ issue events, and 30+ workflow events
- Required at least 8 active months and ≤ 3 human pushers
- Called the GitHub API for each candidate in two stages:
  - **Stage 1**: Basic validation (star count, fork status, language, whether it's archived)
  - **Stage 2**: Quality inspection (README presence and length, test files, CI config, release count, commit message diversity)
- Filtered out known noise patterns: mirrors, backups, dotfiles, status pages, uptime monitors, i18n-only repos

**Result:** The `ghost_repos_v5_final.csv` dataset (401 repos).

This is the version used in the blog post and data explorer.

---

## v6 — Extended date range, tighter noise filters

**What it did:**
- Extended the date range to cover more of 2025 and early 2026 (the raw `bquxjob_412f814a_19d44cadf87.csv` export)
- Tightened a few noise filter thresholds based on patterns spotted in the v5 output
- Same two-stage API verification approach as v5

The v6 BigQuery output is in `data/raw/bquxjob_412f814a_19d44cadf87.csv`. It hasn't been fully scored through the Python pipeline yet, but it's there for future runs.

---

## What the raw CSVs contain

| File | Query version | Rows | Date range |
|------|--------------|------|------------|
| `bq-results-20260327-032336-1774582099303.csv` | Early run | 500 | 2025-01-01 to 2025-08-13 |
| `bquxjob_6df66b77_19d449db63d.csv` | v5 input | 99 | Full 2025 |
| `bquxjob_412f814a_19d44cadf87.csv` | v6 input | 999 | 2025-01-01 to 2026-03-30 |

---

## Running a new query

If you want to run the query yourself, the general structure of the v5/v6 query is:

```sql
SELECT
  repo.name AS repo_name,
  COUNT(*) AS push_events,
  SUM(JSON_EXTRACT_SCALAR(payload, '$.distinct_size')) AS total_commits,
  COUNT(DISTINCT actor.login) AS human_pushers,
  COUNT(DISTINCT FORMAT_DATE('%Y-%m', DATE(created_at))) AS active_months,
  -- ... additional aggregations for PRs, issues, workflows, etc.
FROM `githubarchive.day.*`
WHERE
  _TABLE_SUFFIX BETWEEN '20250101' AND '20260330'
  AND type = 'PushEvent'
  -- ... JOIN with other event types for PR/issue counts
GROUP BY repo.name
HAVING
  active_months >= 8
  AND human_pushers BETWEEN 1 AND 3
  AND push_events BETWEEN 100 AND 5000
  -- ... threshold filters
ORDER BY push_events DESC
LIMIT 1000
```

The actual queries were more complex (multi-CTEs joining PushEvents, PullRequestEvents, IssuesEvents, WorkflowRunEvents) but this gives the shape.
