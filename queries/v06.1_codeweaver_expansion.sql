-- =============================================================================
-- Ghost Repos v6.1: The "CodeWeaver" 2026 Expansion (Final Query)
-- =============================================================================
-- This is the query that produced the 401-repo dataset used in the blog post
-- and data explorer.
--
-- Reference case: knitli/codeweaver
--
-- Key additions over v5:
--   - UNION ALL across 2025 and 2026 data tables to extend the date range.
--     (BigQuery doesn't support wildcard joins across multiple prefixes in a
--     single FROM clause — UNION ALL is the workaround.)
--   - active_months threshold raised from 6 to 8 (stricter consistency filter)
--   - push_events range widened to 150–5000 (catches more at the low end)
--   - Expanded noise filter patterns: template, tutorial, learn-, awesome-,
--     practice, course, assignment, homework
--   - Column names changed: stars_period / forks_period instead of
--     stars_2025 / forks_2025 to reflect the multi-year date range
-- =============================================================================

WITH
  raw_data AS (
    SELECT * FROM `githubarchive.month.2025*`
    UNION ALL
    SELECT * FROM `githubarchive.month.2026*`
  ),
  activity_base AS (
    SELECT
      repo.id AS repo_id,
      ANY_VALUE(repo.name) AS repo_name,
      COUNTIF(type = 'PushEvent') AS push_events,
      SUM(IF(type = 'PushEvent',
        CAST(JSON_EXTRACT_SCALAR(payload, '$.size') AS INT64), 0)) AS total_commits,
      MAX(IF(type = 'PushEvent',
        CAST(JSON_EXTRACT_SCALAR(payload, '$.size') AS INT64), 0)) AS max_commits_in_push,
      COUNTIF(type = 'WatchEvent') AS stars_gained,
      COUNTIF(type = 'ForkEvent') AS forks_gained,
      COUNTIF(type = 'IssuesEvent') AS issue_events,
      COUNTIF(type = 'IssueCommentEvent') AS issue_comment_events,
      COUNTIF(type = 'PullRequestEvent') AS pr_events,
      COUNTIF(type = 'PullRequestReviewEvent') AS pr_review_events,
      COUNTIF(type = 'PullRequestReviewCommentEvent') AS pr_comment_events,
      COUNTIF(type = 'ReleaseEvent') AS release_events,
      COUNTIF(type = 'CreateEvent'
        AND JSON_EXTRACT_SCALAR(payload, '$.ref_type') = 'repository') AS create_events,
      COUNTIF(type = 'CreateEvent'
        AND JSON_EXTRACT_SCALAR(payload, '$.ref_type') IN ('branch', 'tag')) AS branch_tag_creates,
      COUNT(DISTINCT IF(type = 'PushEvent',
        FORMAT_TIMESTAMP('%Y-%m', created_at), NULL)) AS active_months,
      COUNT(DISTINCT IF(type = 'PushEvent',
        FORMAT_TIMESTAMP('%Y-%U', created_at), NULL)) AS active_weeks,
      COUNT(DISTINCT IF(
        type = 'PushEvent'
        AND actor.login NOT LIKE '%[bot]'
        AND actor.login NOT LIKE '%-bot'
        AND actor.login NOT LIKE 'dependabot%'
        AND actor.login NOT LIKE 'renovate%'
        AND actor.login NOT IN ('github-actions', 'web-flow', 'vercel-bot', 'netlify-bot',
                                'semantic-release-bot', 'allcontributors', 'mergify',
                                'codecov', 'snyk-bot', 'greenkeeper', 'kodiakhq'),
        actor.login, NULL
      )) AS human_pushers,
      MIN(created_at) AS first_seen,
      MAX(created_at) AS last_seen
    FROM raw_data
    GROUP BY repo.id
  ),
  scored AS (
    SELECT *,
      (issue_events + issue_comment_events + pr_events + pr_review_events + pr_comment_events)
        AS workflow_events,
      ROUND(SAFE_DIVIDE(total_commits, push_events), 1) AS avg_commits_per_push
    FROM activity_base
    WHERE
      active_months >= 8                              -- raised from 6 in v5
      AND push_events BETWEEN 150 AND 5000            -- widened from 100–3500 in v5
      AND max_commits_in_push <= 200
      AND SAFE_DIVIDE(total_commits, push_events) < 40
      AND human_pushers BETWEEN 1 AND 5
      AND create_events = 0
      AND (issue_events + pr_events) >= 20
      AND issue_events >= 5
      AND pr_events >= 5
      AND stars_gained <= 100
  )
SELECT
  repo_name, push_events, total_commits, avg_commits_per_push,
  active_months, active_weeks,
  stars_gained AS stars_period,   -- renamed from stars_2025
  forks_gained AS forks_period,   -- renamed from forks_2025
  issue_events, pr_events, workflow_events, release_events,
  branch_tag_creates, human_pushers, first_seen, last_seen
FROM scored
WHERE
  NOT REGEXP_CONTAINS(LOWER(repo_name),
    r'(mirror|backup|homebrew|upptime|uptime|status|dotfiles|nixpkgs|linux|kernel|ansible|terraform|exercise|advent-of-code|leetcode|scraper|crawler|data-archive|\.github\.io|auto-commit|autocommit|gentoo|slackbuild|monitor|ppa-|template|tutorial|learn-|awesome-|practice|course|assignment|homework)')
  AND repo_name NOT LIKE CONCAT(SPLIT(repo_name, '/')[SAFE_OFFSET(0)], '/',
                                SPLIT(repo_name, '/')[SAFE_OFFSET(0)])
  AND NOT ENDS_WITH(repo_name, '/.github')
ORDER BY active_months DESC, active_weeks DESC, workflow_events DESC
LIMIT 1000;
