Continue:
* fix and stablize your workflow, op result, and @task
* don't try to save your traces to postgres
    * just save it to logs and have it append to continue writting
* then you can set up an eval script
    * load in the user message, send the mermaids in json file to review
    * and send metadata like how long it took and stuff (all are in your operation result)
    * then you can optimize later


So there are 2 types of workflow
    1. that's need stop on raise (smaller step)
        * parse intent, and planner stuff is one
        * if one fails then it should raise and get send back to the orchestator
        * but what about internal validation? (still need to try-execpt)
        * what about where does the strategy fixing or retries happen
        * within the parse_intent or classification?
    2. and the other don't (main orchestrator)
        * the orchestrator or parent workflow can't raise on failure
        * because you don't want everything to crash and you might
        * use that to send to an LLM to fix or generate a response
A @task decorator should always raise
    * it should be 1 atomic step without lower steps
    * maybe find away to pass in a wrapper or something
    * to write to db if needed



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