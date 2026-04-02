-- =============================================================================
-- Ghost Repos v2: Fixed query — count push events, not commit sizes
-- =============================================================================
-- Key change from v1: use COUNT(*) of push events as the primary activity
-- signal, NOT SUM(payload.size). Push events can't be inflated by history
-- imports the way commit counts can.
--
-- Also added: cap on commits-per-push and max-commits-in-single-push to
-- exclude force-pushes of entire repo histories.
--
-- Result: Got the 500 most push-active repos. Still very noisy — the top
-- results were almost entirely automated bots, CI pipelines, and uptime
-- monitors. But at least the signal was real.
-- =============================================================================

WITH push_activity AS (
  SELECT
    repo.name AS repo_name,
    repo.id AS repo_id,
    COUNT(*) AS push_events,
    SUM(CAST(JSON_EXTRACT_SCALAR(payload, '$.size') AS INT64)) AS total_commits,
    COUNT(DISTINCT actor.login) AS distinct_pushers,
    COUNT(DISTINCT FORMAT_TIMESTAMP('%Y-%m', created_at)) AS active_months,
    MAX(CAST(JSON_EXTRACT_SCALAR(payload, '$.size') AS INT64)) AS max_commits_in_single_push,
    ROUND(SUM(CAST(JSON_EXTRACT_SCALAR(payload, '$.size') AS INT64)) / COUNT(*), 1) AS avg_commits_per_push,
    MIN(created_at) AS first_push_in_period,
    MAX(created_at) AS last_push_in_period
  FROM `githubarchive.month.2025*`
  WHERE
    type = 'PushEvent'
    AND actor.login NOT LIKE '%[bot]'
    AND actor.login NOT LIKE '%bot'
    AND actor.login NOT LIKE 'dependabot%'
    AND actor.login NOT LIKE 'renovate%'
    AND actor.login NOT IN ('github-actions', 'mergify', 'kodiakhq',
                            'snyk-bot', 'codecov', 'greenkeeper',
                            'allcontributors', 'semantic-release-bot',
                            'web-flow')
  GROUP BY repo.name, repo.id
  HAVING
    COUNT(*) >= 200
    AND COUNT(DISTINCT FORMAT_TIMESTAMP('%Y-%m', created_at)) >= 4
    AND MAX(CAST(JSON_EXTRACT_SCALAR(payload, '$.size') AS INT64)) <= 500
    AND (SUM(CAST(JSON_EXTRACT_SCALAR(payload, '$.size') AS INT64)) / COUNT(*)) < 50
    AND COUNT(DISTINCT actor.login) <= 10
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
  p.repo_name, p.push_events, p.total_commits, p.avg_commits_per_push,
  p.max_commits_in_single_push, p.distinct_pushers, p.active_months,
  COALESCE(s.stars_gained, 0) AS stars_gained_2025,
  COALESCE(f.forks_gained, 0) AS forks_gained_2025,
  p.first_push_in_period, p.last_push_in_period
FROM push_activity p
LEFT JOIN star_activity s ON p.repo_id = s.repo_id
LEFT JOIN fork_activity f ON p.repo_id = f.repo_id
LEFT JOIN create_events c ON p.repo_id = c.repo_id
WHERE
  COALESCE(s.stars_gained, 0) <= 5
  AND c.repo_id IS NULL
  -- Exclude self-named repos (org/org pattern — often mirrors or personal forks)
  AND p.repo_name NOT LIKE CONCAT(SPLIT(p.repo_name, '/')[SAFE_OFFSET(0)], '/', SPLIT(p.repo_name, '/')[SAFE_OFFSET(0)])
  AND LOWER(p.repo_name) NOT LIKE '%mirror%'
  AND LOWER(p.repo_name) NOT LIKE '%backup%'
  AND LOWER(p.repo_name) NOT LIKE '%homebrew-%'
  AND LOWER(p.repo_name) NOT LIKE '%.github.io'
  AND LOWER(p.repo_name) NOT LIKE '%upptime%'
  AND LOWER(p.repo_name) NOT LIKE '%dotfiles%'
  AND LOWER(p.repo_name) NOT LIKE '%nixpkgs%'
  AND LOWER(p.repo_name) NOT LIKE '%linux%'
  AND LOWER(p.repo_name) NOT LIKE '%ansible-%'
  AND LOWER(p.repo_name) NOT LIKE '%advent-of-code%'
  AND LOWER(p.repo_name) NOT LIKE '%leetcode%'
ORDER BY p.push_events DESC
LIMIT 500;
