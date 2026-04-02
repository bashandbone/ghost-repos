-- =============================================================================
-- Ghost Repos v1: First attempt
-- =============================================================================
-- Run this on Google BigQuery against the public GH Archive dataset.
-- Free tier: 1 TiB/month. This query scans ~200-400GB depending on date range.
-- Start with a smaller date range (1 month) to test, then expand.
--
-- PROBLEM WITH THIS VERSION: SUM(payload.size) is broken as a commit signal.
-- Pushing a full repo clone reports the entire commit history as a single push
-- event, so every result had 100M+ "commits". This led directly to v2.
-- =============================================================================

WITH push_activity AS (
  SELECT
    repo.name AS repo_name,
    repo.id AS repo_id,
    COUNT(*) AS push_events,
    SUM(CAST(JSON_EXTRACT_SCALAR(payload, '$.size') AS INT64)) AS total_commits,
    COUNT(DISTINCT actor.login) AS distinct_pushers,
    COUNT(DISTINCT FORMAT_TIMESTAMP('%Y-%m', created_at)) AS active_months,
    MIN(created_at) AS first_push_in_period,
    MAX(created_at) AS last_push_in_period
  FROM `githubarchive.month.2025*`
  WHERE
    type = 'PushEvent'
    AND actor.login NOT LIKE '%[bot]'
    AND actor.login NOT LIKE '%bot'
    AND actor.login NOT IN ('dependabot', 'renovate', 'greenkeeper', 'snyk-bot',
                            'codecov', 'github-actions', 'mergify', 'kodiakhq')
  GROUP BY repo.name, repo.id
  HAVING
    SUM(CAST(JSON_EXTRACT_SCALAR(payload, '$.size') AS INT64)) >= 200
    AND COUNT(DISTINCT FORMAT_TIMESTAMP('%Y-%m', created_at)) >= 3
),
star_activity AS (
  SELECT repo.name AS repo_name, repo.id AS repo_id, COUNT(*) AS stars_gained
  FROM `githubarchive.month.2025*`
  WHERE type = 'WatchEvent'
  GROUP BY repo.name, repo.id
),
fork_activity AS (
  SELECT repo.name AS repo_name, repo.id AS repo_id, COUNT(*) AS forks_gained
  FROM `githubarchive.month.2025*`
  WHERE type = 'ForkEvent'
  GROUP BY repo.name, repo.id
),
create_events AS (
  SELECT DISTINCT repo.id AS repo_id
  FROM `githubarchive.month.2025*`
  WHERE type = 'CreateEvent' AND JSON_EXTRACT_SCALAR(payload, '$.ref_type') = 'repository'
)

SELECT
  p.repo_name,
  p.total_commits,
  p.push_events,
  p.distinct_pushers,
  p.active_months,
  COALESCE(s.stars_gained, 0) AS stars_gained_2025,
  COALESCE(f.forks_gained, 0) AS forks_gained_2025,
  CASE
    WHEN COALESCE(s.stars_gained, 0) = 0 THEN p.total_commits
    ELSE ROUND(p.total_commits / s.stars_gained, 1)
  END AS commits_per_star,
  p.first_push_in_period,
  p.last_push_in_period
FROM push_activity p
LEFT JOIN star_activity s ON p.repo_id = s.repo_id
LEFT JOIN fork_activity f ON p.repo_id = f.repo_id
LEFT JOIN create_events c ON p.repo_id = c.repo_id
WHERE
  COALESCE(s.stars_gained, 0) <= 5
  AND c.repo_id IS NULL
  AND p.repo_name NOT LIKE CONCAT(SPLIT(p.repo_name, '/')[SAFE_OFFSET(0)], '/', SPLIT(p.repo_name, '/')[SAFE_OFFSET(0)])
  AND LOWER(p.repo_name) NOT LIKE '%mirror%'
  AND LOWER(p.repo_name) NOT LIKE '%backup%'
  AND LOWER(p.repo_name) NOT LIKE '%homebrew-%'
  AND LOWER(p.repo_name) NOT LIKE '%.github.io'
  AND LOWER(p.repo_name) NOT LIKE '%upptime%'
  AND LOWER(p.repo_name) NOT LIKE '%statuspage%'
  AND LOWER(p.repo_name) NOT LIKE '%dotfiles%'
  AND p.distinct_pushers >= 1
ORDER BY p.total_commits DESC
LIMIT 500;

-- Note: v1 also included commented-out guidance for Steps 2 and 3:
-- Step 2 suggested verifying total star counts via GitHub API (since the query
-- only captures stars GAINED in the query period, not total lifetime stars).
-- Step 3 proposed a ghost_score = total_commits / log10(total_stars + 2) formula
-- for ranking results. Both ideas fed into the Python verification script
-- that was built alongside v4/v5.
