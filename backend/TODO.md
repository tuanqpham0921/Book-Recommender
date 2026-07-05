Continue:
* don't try to save your traces to postgres
    * just save it to logs and have it append to continue writting
* then you can set up an eval script
    * load in the user message, send the mermaids in json file to review
    * and send metadata like how long it took and stuff (all are in your operation result)
    * then you can optimize later

Note:
* currently your workflow and operation is fine
    * it could be better but we can deal it more stuff later
    * right now it supports run_async_step (need a @task for non failure)
    * steps also has to be OperationalResult in add step to help detect that

Reminder:
1. need to create one executor for @task and workflow
2. add timeout to @task and @workflow (should be able to handle them)
3. execution sql can just hold things like time, token usage, edit needed, run-time errors
    * don't store the full result in there
    * make it a background task on a seperate thread
4. remove the private attributes (keep it in the output)
    * might need to use create instead of parse
    * this  an be for later, when you actually need to load in buffer
Eval and deployment testing:
1. create a way to run all your test queries (prod mode)
2. show rejected quries and resuls
2. then a script to send all those to the frontend for you to review
3. deploy your app without DB
=======================================================================

Unit Test:
5. test your WorkFlow and decorator last
    * focus on raising and throwing errors (logic first)
    * check your logger

lower priority:
* test your sse stream (might change later, and working right now)
* test your ingestion (need to re-write to use workflow)

=======================================================================


Eval:
1. test repeated queries (find dune, and find dune)
2. add more request schemas (see how the planner do)
3. test the response of reject reasons

=======================================================================

Front End:
1. test your markdown and how it handle spacings (formatting)
    * nested bullet points was one
    * two dividers back to back? only one should show (or if there is no text before)
2. test error messages
3. test if your backend is not running or stalling

=======================================================================

Claude Suggestions (code review findings):
2. [BUG] Token usage double-counted in app/common/workflow.py:64
   * run_llm_call adds token_usage twice (once via add_step, once manually) — remove line 64
3. [LEAK] Cancel `orchestrator_task` on exception in chat_message.py:39
   * task keeps running into a dead SSE stream on client disconnect
4. [SILENT ERROR] Replace HTTPException in SSE generator with a yield error event (chat_message.py:40)

=======================================================================

Features (not in code):
* do openAI always make new lines at the end?
3. goal is to test and see the ochestration router
    actual task nodes implmentation is for later


=======================================================================

Claude codebase sweep (2026-07-05) — critical or worth mentioning only:

BUGS (fix before eval — these crash or mislabel real runs):
2. [MISLABEL] Orchestrator misses crashes buried under StepFailure aborts
   * after a child workflow aborts via StepFailure, its top-level envelope has
     runtime_error=None — the real crash (e.g. OpenAI exception) lives in steps[i]
   * main.py `if parse_result.run_time_error:` therefore sends the "system declined"
     message for genuine crashes
   * fix: add recursive `has_runtime_error()` on OperationResult, branch on that

BEFORE EVAL (the eval script depends on these):
4. Saved results drop the step trail: save_conversation_result pops "steps" —
   the timings/token/failure metadata the eval wants is exactly in there.
   Add a derived compact trail (name, ok, duration, tokens per step) instead of the full tree.
5. Failure paths never save: save_chat_messages/save_conversation_result only run on
   success and handled-without-planning. Rejected/failed queries (the interesting eval
   cases!) leave no artifact. Save in one place that all exits pass through.
6. Fixed filenames (conversation_result_dev.json) overwrite every run — eval over a
   query set needs per-session names or append mode (matches the "Continue" note up top).
7. Buffered/refused are terminal: buffer_goals and strategy buffer are captured but
   nothing consumes them. Fine to defer the retry loop — but the eval should count them.

ANNOTATION LIES (pyright basic would catch all of these — consider adding it as a dev dep):
8. to_llm_messages() declared `-> list[AssistantMessage]`, returns a dict (parse_intent.py:160)
9. OrchestrationOutput.to_summary() declared `-> dict`, returns None (main.py:35 TODO)
10. @task is typed `Callable[..., Any]` — erases every decorated signature; use ParamSpec
    so arg mistakes on tasks become static errors

SMALL CLEANUPS:
11. _invalid_target_goal is captured but never surfaced (no refuse/details/output) —
    either report like output.invalid does for strategies, or delete the capture
12. Field(example=...) deprecation (4 warnings) — json_schema_extra before pydantic v3
13. test_already_constructed_instance_is_rejected asserts the OPPOSITE of its name
    (instances are accepted as valid now) — rename it + the stale class docstring above it
14. Document the one-shot Workflow contract: output lists append-accumulate, so a retry
    means a fresh instance — worth a docstring before eval scripts loop over workflows
15. (resolved since last review: token double-count in run_llm_call is gone —
    item 2 under "Claude Suggestions" above can be checked off)

=======================================================================