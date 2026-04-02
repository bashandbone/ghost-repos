-- =============================================================================
-- Ghost Repos v4: The "Soul-Poured" Refinement
-- =============================================================================
-- New approach: consolidate all event types into a single scan of the table
-- (one pass, all events) instead of CTEs that scan the table multiple times.
-- More efficient and cheaper on BigQuery.
--
-- Key insight: require at least some issue or PR activity.
-- Real projects generate issues and PRs — bots usually don't.
-- This kills a lot of uptime monitors and scrapers.
--
-- Star cap raised to 100 to capture slow-burn projects that have built a
-- small following over years (not just zero-star repos).
--
-- Still noisy: Renovate and Dependabot create real PRs, so bot-heavy repos
-- still slipped through. Needed a harder workflow activity threshold (v5).
-- =============================================================================

WITH
  activity_base AS (
    SELECT
      repo.id AS repo_id,
      ANY_VALUE(repo.name) AS repo_name,
      COUNTIF(type = 'PushEvent') AS push_events,
      COUNTIF(type = 'WatchEvent') AS stars_gained,
      COUNTIF(type = 'ForkEvent') AS forks_gained,
      COUNTIF(type IN ('IssuesEvent', 'IssueCommentEvent')) AS issue_events,
      COUNTIF(type IN ('PullRequestEvent', 'PullRequestReviewEvent')) AS pr_events,
      COUNTIF(type = 'CreateEvent'
        AND JSON_EXTRACT_SCALAR(payload, '$.ref_type') = 'repository') AS create_events,
      COUNT(DISTINCT IF(type = 'PushEvent',
        FORMAT_TIMESTAMP('%Y-%m', created_at), NULL)) AS active_months,
      COUNT(DISTINCT IF(type = 'PushEvent',
        FORMAT_TIMESTAMP('%Y-%U', created_at), NULL)) AS active_weeks,
      SUM(IF(type = 'PushEvent',
        CAST(JSON_EXTRACT_SCALAR(payload, '$.size') AS INT64), 0)) AS total_commits,
      MAX(IF(type = 'PushEvent',
        CAST(JSON_EXTRACT_SCALAR(payload, '$.size') AS INT64), 0)) AS max_commits_in_push,
      COUNT(DISTINCT IF(
        type = 'PushEvent'
        AND actor.login NOT LIKE '%[bot]'
        AND actor.login NOT LIKE '%-bot'
        AND actor.login NOT IN ('github-actions', 'web-flow', 'vercel-bot',
                                'netlify-bot'),
        actor.login, NULL
      )) AS human_pushers,
      MIN(created_at) AS first_seen,
      MAX(created_at) AS last_seen
    FROM `githubarchive.month.2025*`
    GROUP BY repo.id
  ),
  filtered_gems AS (
    SELECT * FROM activity_base
    WHERE
      active_months >= 6
      AND push_events BETWEEN 100 AND 3500
      AND stars_gained <= 100
      AND human_pushers BETWEEN 1 AND 5
      AND (issue_events > 0 OR pr_events > 0)   -- must have some project activity
      AND create_events = 0                       -- not a brand-new repo
      AND max_commits_in_push <= 200
      AND (total_commits / NULLIF(push_events, 0)) < 40
  )
SELECT
  repo_name, push_events, total_commits, active_months, active_weeks,
  stars_gained AS stars_2025, issue_events, pr_events, human_pushers,
  first_seen, last_seen
FROM filtered_gems
WHERE
  NOT REGEXP_CONTAINS(LOWER(repo_name),
    r'(mirror|backup|homebrew|upptime|status|dotfiles|nixpkgs|linux|ansible|terraform|config|exercise|advent-of-code|leetcode|scraper|crawler|data-archive)')
  AND repo_name NOT LIKE CONCAT(SPLIT(repo_name, '/')[SAFE_OFFSET(0)], '/',
                                SPLIT(repo_name, '/')[SAFE_OFFSET(0)])
ORDER BY active_months DESC, active_weeks DESC, push_events DESC
LIMIT 100;
