Continue:

Keep what you have. the validators logic
* the structure is there so you can just change the logic later
* maybe use create() instead of parse? 
    * but it's not a big deal for v1
    * and forget about tools=[req1, req2, ...] for now
    * we can easily implement that in the future
* do think about strategy request
    * what is the LLM suppose to do if it can't fill?
    * bc it's required and stuff
    * so maybe a field for refusal or create a node for unfillable?


4. before testing your BaseRequest
   * make a re-use able validator (should be good for list, str, etc...)
   * make sure you keep track of what comes back from LLM

Current:
1. create a way to run all your test queries (pod mode)
2. show rejected quries and resuls
2. then a script to send all those to the frontend for you to review
3. deploy your app without DB

Reminder:
1. need to create one executor for @task and workflow
2. add timeout to @task and @workflow (should be able to handle them)
=======================================================================

Unit Test:
4. test the base request and request schemas pre-post validators
    * create fake openAI response (with ints instead of strs for example)
    * more than the limit the amount of strings
5. test your WorkFlow and decorator last
    * focus on raising and throwing errors (logic first)
    * check your logger
6. tests all tools have docstrings at least

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