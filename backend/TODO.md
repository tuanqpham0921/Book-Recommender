Continue:
* current goal is to have fake responses 
* the code is able to load them in
* and we can load it back in the front end for testings

* review SSE unit tests
* test asyncio cancel and time out and maybe concurrency issues?
* might need to move it to generate_reponse instead
* make orchestration into a workflow?

* rename your @task to @op_task or something (so no name conflicting)
* rename OperationalResult to OperationResult
* workflow self.result to self.op_result (so it's clearer)
* rename all the issues to feedback
* use TD for long concurrency, LR for long depends on
    * can just make a indegree nodes level

Bugs:
* UI: chat input is scrollable when empty

=======================================================================

Reminder:
* changing review path still finish the query
    * expected? since it's not refreshing the page for a new session
    * for dev review is fine to get all the current chat_runs
        * for prod, we need to make it limit to just test suites?
* currently your workflow and operation is fine
    * it could be better but we can deal it more stuff later
    * right now it supports run_async_step (need a @task for non failure)
    * steps also has to be OperationalResult in add step to help detect those
* orchestrator is where you can load in cls and workflow for other things as well
    * saving to db, feedback code etc
1. need to create one executor for @task and workflow
    * do this later once you have time out and flush out more stuff
2. add timeout to @task and @workflow (should be able to handle them)
3. remove the private attributes (keep it in the output)
    * might need to use create instead of parse
    * this  an be for later, when you actually need to load in buffer
4. your current interupt works. But it will lose progress in the child workflow
    * this is because you are not self.add_step before the run (incremental changes)
    * you only add the operationalresult after it has finish
        run_async_step, await func, add_steps
        so you'll lose all the await func execution
    * this is fine for now, still save some repeated work
    * but if you want better checkpoint, you need to add_steps(child_workflow.result) the operational result (reference to that obj)
        * you also need to make the workflow make incremental edits to it
        * this can come later, since it will require some re-thinking of your workflow (like returning op_result and appending or overwritting etc...)
    * or you could just do a run_workflow instead
        * which you can just add reference in the steps before run_async_step
5. there's something wrong with how you overwrite the self.result messages
    * figure out where the put in details vs message
    * maybe push it to details with "prev message: ..."
    * change your app/workflow to not overwrite and make sure tests passes 

Ideas:
* mermaid optimization (TD for high concurrent, LR for high depends_on)
* once you have resume/checkpoint, you might need to move some stuff around
    * you might need to have the model validate do the DAG processing
    * that way you can pick up from orchestrator and continue
    * but then you also needs steps as config, so you know what to run next etc...
* add a tool catalog (as a UI or command query)
* recommendation node and re-rank is ideal place for human in the loop
    * if there are a lot of candidates, we can ask the user what they like
* always need to clamp a recommendation node for books related
    * feels more consumer like (do you have Dune? - yes, and I think you'll like these)
    * maybe for later versions

=======================================================================

lower priority:
* test your ingestion (need to re-write to use workflow)

=======================================================================

Features (not in code):
* do openAI always make new lines at the end?
3. goal is to test and see the ochestration router
    actual task nodes implmentation is for later


=======================================================================

Once everything is good, organize and review all your unit tests
but after you have db saved, and eval tests set up
    * need to format and review name, comments carefully
    * you should have a way to navigate all your tests (probably at the top)
    * with all pages marker or seperators

=======================================================================

Code review findings (2026-07-10):

Fix first (security, cheap and exploitable):
* db/stores/utils.py:36,44,62,66,111,126,162,168 - SQL injection: build_title_search/
  build_author_search/apply_book_filters splice user strings into text(f"'{...}'")
  instead of binding params. `' OR 1=1 --` breaks out of the literal.
* app/main.py:55, config/settings/app.py:8 - ALLOW_ORIGINS is a raw str, not list[str].
  CORSMiddleware does substring match on a plain string, not exact match, once you
  configure more than one origin -> real CORS bypass. Split on comma before passing in.
* db/stores/base_store.py:19-20 - _execute_statement print()s fully compiled SQL with
  literal_binds=True (real param values) on every query, in every environment. Remove
  or gate behind logger.debug.

Correctness bugs:
* common/utils/json_handler.py:52,66 - file_name.rstrip(".json") strips a char set, not
  the literal suffix. Use removesuffix(".json").
* db/stores/utils.py:58 - build_author_search references model.author (singular);
  BookModel only has `authors`. Dead code, breaks as soon as something calls it.
* config/constants.py:66-67 - BookGuides.__str__ returns "BookConstraints:\n" (copy-paste
  from BookConstraints.__str__) - wrong section header shown to the LLM in prompts.
* common/operation.py:65-73 - check_output_type has unreachable branch: early return on
  `output is None` makes the later `output is None and output_type is None` dead.
* common/context.py:42-48 - AppContext.__aenter__ has ping_services() entirely commented
  out - app reports ready without checking OpenAI/DB connectivity at boot.
* clients/openai_client.py:54 - chat completions have no semaphore (embeddings do) - no
  concurrency limit, can blow past OpenAI rate limits.
* clients/openai_client.py:116 - ping() hardcodes "gpt-5-nano" instead of
  settings.openai.BASE_MODEL.
* db/stores/base_store.py:17-24 - try/except Exception as e: raise e does nothing, either
  delete or actually log context on failure.

Consistency / tech debt:
* db/schema/models.py:19-43 - Column(index=True) on several BookModel columns does
  nothing since tables/indexes are created via raw SQL (01/02.sql), not
  Base.metadata.create_all - misleading, and filters on published_year/average_rating/
  genre run unindexed. Add real indexes or drop the flag.
* db/stores/book_store.py:52-83 - search_by_book_filter loops one DB round-trip per
  author instead of one query + grouping/ranking (apply_book_filters already ORs
  across authors).
* common/utils/identifiers.py:12-13 - uuid_8() is 32 bits of entropy, used as PK for
  chat_runs.chat_id and feedback.id - collision = silent failed insert well before
  "web scale." Consider a longer id.
* app/api/schemas/external.py:26 - FeedbackIn.message has no max_length (ChatIn's length
  check also lives ad hoc in the route, not the schema - move it in for consistency).
* app/common/sse_stream.py:69-73 - send_chars streams one char at a time with
  asyncio.sleep per char - hundreds of tiny SSE events + real added latency for
  long responses. Consider chunking by word if this becomes a latency complaint.

Test coverage gaps (new, not already in this file):
* db/stores/ - zero tests for book_store.py, chat_run_store.py, feedback_store.py,
  base_store.py, utils.py (the query-builder with the SQL injection above).
* app/api/routes/ - only chat_message.py has a test; session.py, chat_run.py,
  feedback.py, health.py have none.
* app/domains/{books,project,users}/schemas/ - no tests for domain request-schema
  validators.
* common/context.py (AppContext), db/bootstrap.py, db/readiness.py - untested.