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
5. make sure that feedback and liked stuff can just go to json
    feedback
        {"session": "id", "comments": "....", maybe chat_id}
    liked/dislike
        * could go in a sql db instead

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
10. @task is typed `Callable[..., Any]` — erases every decorated signature; use ParamSpec
    so arg mistakes on tasks become static errors

=======================================================================

Once everything is good, organize and review all your unit tests
but after you have db saved, and eval tests set up
    * need to format and review name, comments carefully
    * you should have a way to navigate all your tests (probably at the top)
    * with all pages marker or seperators