-- get the mermaid diagram
SELECT orchestration -> 'output' ->> 'diagram' AS mermaid
FROM chat_runs
WHERE chat_id = 'chat_c8a0f07e' AND session_id = 'c74f8348';

-- average parse_intent and strategy_classification duration
SELECT
    step ->> 'name' AS workflow,
    AVG((step ->> 'duration')::float) AS avg_duration_s,
    COUNT(*) AS n
FROM chat_runs,
     jsonb_array_elements(orchestration -> 'steps') AS step
WHERE step ->> 'name' IN (
    'app.domains.planner.parse_intent.PlanJaneExecutor',
    'app.domains.planner.strategy_classification.StrategyClassificationWorkflow'
)
GROUP BY step ->> 'name';

-- get the number of runtime errors in steps
-- NOTE: currently have none so this is just template
SELECT
    step ->> 'name' AS workflow,
    step -> 'runtime_error' ->> 'type' AS error_type,
    COUNT(*) AS n
FROM chat_runs,
     jsonb_array_elements(orchestration -> 'steps') AS step
WHERE step ->> 'name' IN (
    'app.domains.planner.parse_intent.PlanJaneExecutor',
    'app.domains.planner.strategy_classification.StrategyClassificationWorkflow'
)
AND step -> 'runtime_error' IS NOT NULL
GROUP BY step ->> 'name', step -> 'runtime_error' ->> 'type'
ORDER BY workflow, n DESC;

-- get the length of the issues array jsonb
SELECT chat_id, jsonb_array_length(issues) AS issue_count
FROM chat_runs
ORDER BY issue_count DESC;

-- linking feedback to chat_runs example
-- get all feedback for chat_runs that were liked
SELECT
    cr.chat_id,
    f.*
FROM chat_runs AS cr
JOIN feedback AS f
    ON cr.chat_id = f.chat_id
WHERE cr.liked = TRUE
ORDER BY f.created_at;

--- linking feedback to chat_runs example
--- get all the chat_runs where feedback title is 'Recommendation'
SELECT
    cr.chat_id,
    f.*
FROM feedback AS f
JOIN chat_runs AS cr
    ON cr.chat_id = f.chat_id
WHERE f.title = 'Recommendation'
ORDER BY f.created_at;