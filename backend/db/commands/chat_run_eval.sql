-- Overall chat_runs eval summary: token/time volume and averages, pass/fail counts
SELECT
    COUNT(*) AS total_runs,
    SUM(total_tokens) AS total_tokens,
    ROUND(AVG(total_tokens)::numeric, 1) AS avg_tokens,
    ROUND(SUM(duration_s)::numeric, 1) AS total_duration_s,
    ROUND(AVG(duration_s)::numeric, 2) AS avg_duration_s,
    COUNT(*) FILTER (WHERE ok IS TRUE) AS num_ok,
    COUNT(*) FILTER (WHERE ok IS NOT TRUE) AS num_not_ok,
    COUNT(*) FILTER (WHERE runtime_error IS NOT NULL) AS num_runtime_error,
    COUNT(*) FILTER (WHERE runtime_error IS NULL) AS num_no_runtime_error
FROM chat_runs;

-- breakdown by ok / not ok
SELECT
    ok,
    COUNT(*) AS n,
    SUM(total_tokens) AS total_tokens,
    ROUND(AVG(total_tokens)::numeric, 1) AS avg_tokens,
    ROUND(AVG(duration_s)::numeric, 2) AS avg_duration_s
FROM chat_runs
GROUP BY ok
ORDER BY ok;

-- breakdown by whether a runtime_error was recorded
SELECT
    (runtime_error IS NOT NULL) AS has_runtime_error,
    COUNT(*) AS n,
    ROUND(AVG(duration_s)::numeric, 2) AS avg_duration_s
FROM chat_runs
GROUP BY (runtime_error IS NOT NULL);

-- most common runtime_error values
SELECT
    runtime_error,
    COUNT(*) AS n
FROM chat_runs
WHERE runtime_error IS NOT NULL
GROUP BY runtime_error
ORDER BY n DESC;

-- chat_runs row size
-- ensure that it's not alot
SELECT
    chat_id,
    pg_column_size(t.*)              AS row_bytes,
    pg_column_size(planner)          AS planner_bytes,
    pg_column_size(tasks)            AS tasks_bytes
FROM chat_runs t
ORDER BY row_bytes DESC
LIMIT 20;
