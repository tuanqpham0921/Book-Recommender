Currently being ignore by git
need to set up a test commands and structure it better later

has raw .sql data, and is useful for future and keeping track of things

The flow:

1. run the test suites (make query-suite / query-suite-all)
    * the runner records one test_runs row per query: chat_id (FK to
      chat_runs) + suite_name + suite_case_id — skip with --no-record
2. post-process into the node-expectation report: make suite-eval
    * joins test_runs with chat_runs and diffs each run's accepted goal
      types against expected_nodes in the suite JSONs (matched/missing/extra)
    * includes the commit sha, per-case query/difficulty from the JSON,
      and match/mismatch counts per suite
    * saved to evals/results/eval_<timestamp>.md; latest run per case by
      default; ARGS="--all" for every run, ARGS="--output <path>" to choose
      the file
3. dump both chat_runs and feedback
    * need to dump the console somehow
    * before it overwrites
    * (test_runs cascades away when chat_runs rows are deleted)
4. make a personal review.md
    * TODO: need a better structure later
    * maybe even a jupyter notebook
5. ask claude to review if you want

