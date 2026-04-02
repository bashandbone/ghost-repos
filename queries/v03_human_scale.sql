-- =============================================================================
-- Ghost Repos v3: Human-scale activity
-- =============================================================================
-- Key fix from v2: CAP push events at a human-plausible maximum (2500).
-- Even the most productive developer isn't pushing 5,000 times in 8 months.
-- If a repo is hitting that ceiling, it's almost certainly automated.
--
-- Also: sort by active_months DESC (consistency over raw volume) and add
-- issue/PR event counts to start surfacing project engagement signals.
--
-- Still noisy: uptime monitors, scraper repos, and status pages all stay
-- under the push cap. The noise filter list grew, but wasn't enough.
-- =============================================================================

WITH push_activity AS (
  SELECT
    repo.name AS repo_name, repo.id AS repo_id,
    COUNT(*) AS push_events,
    SUM(CAST(JSON_EXTRACT_SCALAR(payload, '$.size') AS INT64)) AS total_commits,
    ROUND(SUM(CAST(JSON_EXTRACT_SCALAR(payload, '$.size') AS INT64)) / COUNT(*), 1) AS avg_commits_per_push,
    MAX(CAST(JSON_EXTRACT_SCALAR(payload, '$.size') AS INT64)) AS max_commits_in_single_push,
    COUNT(DISTINCT actor.login) AS distinct_pushers,
    COUNT(DISTINCT FORMAT_TIMESTAMP('%Y-%m', created_at)) AS active_months,
    COUNT(DISTINCT FORMAT_TIMESTAMP('%Y-%W', created_at)) AS active_weeks,
    MIN(created_at) AS first_push_in_period,
    MAX(created_at) AS last_push_in_period
  FROM `githubarchive.month.2025*`
  WHERE
    type = 'PushEvent'
    AND actor.login NOT LIKE '%[bot]'
    AND actor.login NOT LIKE '%bot'
    AND actor.login NOT LIKE 'dependabot%'
    AND actor.login NOT LIKE 'renovate%'
    AND actor.login NOT IN ('github-actions', 'mergify', 'kodiakhq', 'snyk-bot', 'codecov',
                            'greenkeeper', 'allcontributors', 'semantic-release-bot', 'web-flow')
  GROUP BY repo.name, repo.id
  HAVING
    COUNT(*) BETWEEN 200 AND 2500             -- cap removes extreme automation
    AND COUNT(DISTINCT FORMAT_TIMESTAMP('%Y-%m', created_at)) >= 6
    AND MAX(CAST(JSON_EXTRACT_SCALAR(payload, '$.size') AS INT64)) <= 200
    AND (SUM(CAST(JSON_EXTRACT_SCALAR(payload, '$.size') AS INT64)) / COUNT(*)) < 30
    AND COUNT(DISTINCT actor.login) BETWEEN 1 AND 5
),
star_activity AS (
  SELECT repo.name AS repo_name, repo.id AS repo_id, COUNT(*) AS stars_gained
  FROM `githubarchive.month.2025*` WHERE type = 'WatchEvent'
  GROUP BY repo.name, repo.id
),
fork_activity AS (
  SELECT repo.name AS repo_name, repo.id AS repo_id, COUNT(*) AS forks_gained
  FROM `githubarchive.month.2025*` WHERE type = 'ForkEvent'
  GROUP BY repo.name, repo.id
),
create_events AS (
  SELECT DISTINCT repo.id AS repo_id
  FROM `githubarchive.month.2025*`
  WHERE type = 'CreateEvent' AND JSON_EXTRACT_SCALAR(payload, '$.ref_type') = 'repository'
),
issue_activity AS (
  SELECT repo.id AS repo_id, COUNT(*) AS issue_events
  FROM `githubarchive.month.2025*`
  WHERE type IN ('IssuesEvent', 'IssueCommentEvent')
  GROUP BY repo.id
),
pr_activity AS (
  SELECT repo.id AS repo_id, COUNT(*) AS pr_events
  FROM `githubarchive.month.2025*`
  WHERE type IN ('PullRequestEvent', 'PullRequestReviewEvent')
  GROUP BY repo.id
)
SELECT
  p.repo_name, p.push_events, p.total_commits, p.avg_commits_per_push, p.max_commits_in_single_push,
  p.distinct_pushers, p.active_months, p.active_weeks,
  COALESCE(s.stars_gained, 0) AS stars_gained_2025,
  COALESCE(f.forks_gained, 0) AS forks_gained_2025,
  COALESCE(i.issue_events, 0) AS issue_events,
  COALESCE(pr.pr_events, 0) AS pr_events,
  p.first_push_in_period, p.last_push_in_period
FROM push_activity p
LEFT JOIN star_activity s ON p.repo_id = s.repo_id
LEFT JOIN fork_activity f ON p.repo_id = f.repo_id
LEFT JOIN create_events c ON p.repo_id = c.repo_id
LEFT JOIN issue_activity i ON p.repo_id = i.repo_id
LEFT JOIN pr_activity pr ON p.repo_id = pr.repo_id
WHERE
  COALESCE(s.stars_gained, 0) <= 5
  AND c.repo_id IS NULL
  AND p.repo_name NOT LIKE CONCAT(SPLIT(p.repo_name, '/')[SAFE_OFFSET(0)], '/', SPLIT(p.repo_name, '/')[SAFE_OFFSET(0)])
  AND NOT REGEXP_CONTAINS(LOWER(p.repo_name), r'(mirror|backup|homebrew|upptime|uptime|status|dotfiles|nixpkgs|linux|kernel|ansible|terraform|exercise|advent-of-code|leetcode|scraper|crawler|data-archive|auto-commit|autocommit|monitor)')
ORDER BY p.active_months DESC, p.active_weeks DESC, p.push_events DESC
LIMIT 1000;
