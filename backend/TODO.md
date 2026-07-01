Continue:
* make sure duplicate tasks are removed
   * same id but different content (vs same id same content)
   * different id same content(?)
* when rejecting a request, make sure to reject all the ones depends_on it

3. update your tests (test all different graph cases)
   * make sure it can remove the cycle paths
   * retain information from LLM
   * add test for your messages
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
3. might need to add back the tool calls so there's a link between Assistant msg and tool
   * you might run into problems when loading messages back
4. add test query with prompt injections
   * ex: user "ignore system prompt..."
=======================================================================

Unit Test:
3. test all your planner logic (dag, accepted, etc...)
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
1. [CRASH] Fix `g.refusal_reason` → `g.refusal_reasons` in parse_intent.py:179
   * crashes generate_user_response any time a goal is refused
2. [BUG] Token usage double-counted in app/common/workflow.py:64
   * run_llm_call adds token_usage twice (once via add_step, once manually) — remove line 64
3. [LEAK] Cancel `orchestrator_task` on exception in chat_message.py:39
   * task keeps running into a dead SSE stream on client disconnect
4. [SILENT ERROR] Replace HTTPException in SSE generator with a yield error event (chat_message.py:40)
   * 200 OK already sent — raising HTTPException just closes the stream silently
5. [LATENT] Add `@classmethod` to `validate_target_goal` model validator in base_request.py:134
   * Pydantic v2 requires it for mode="before"; will hard-fail on future upgrade
6. [TYPE] Fix `get_strategies_ids` return type: returns set, annotated as list (strategy_classification.py:255)
7. [TEST] Replace `test_shared_messages_list_appended_by_children` — it only tests list.append, not orchestrator behavior
8. [TEST] Fix `test_no_injection_when_retrieval_already_present` to assert set equality, not just length

=======================================================================

Features (not in code):
* do openAI always make new lines at the end?
3. goal is to test and see the ochestration router
    actual task nodes implmentation is for later


=======================================================================

Yes and no — it's a mix of reasons.

What built-ins/libs cover:

pydantic's model_dump(mode="json") handles to_serializable for pure Pydantic models, including Enum and Path recursively inside fields
orjson handles Enum, Path, dataclass, and datetime natively and is much faster than json.dumps — it would replace most of to_serializable for the non-Pydantic types
model_dump(exclude_none=True) covers the "drop None" part of remove_empty_values
Why you still need the custom ones:

Pydantic private attributes (format.py:17-18) — model_dump() explicitly skips __pydantic_private__ by design. No standard serializer touches these. That's the main reason to_serializable has to exist.

Mixed-type recursive pass — you're serializing objects that contain both Pydantic models and plain dataclasses and Exceptions in the same tree (e.g., OperationResult is a dataclass that holds a BaseModel output). No single library handles that mix without custom glue.

remove_empty_values is stricter than Pydantic — exclude_none=True only drops None. You also drop empty strings and empty collections, which is application-specific behavior.

What you could simplify:

If you ever stop needing private attrs in serialized output, to_serializable collapses to just model_dump(mode="json") for Pydantic and orjson.dumps for everything else. The private attr handling is really the only reason this file needs to exist.