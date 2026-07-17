Continue:

    * understand the integration tests more
        * how I set up a away to mock end-to-end tests
    * you should split up tests and queries better (endpoint)
    * there should be structure inputs/ouputs and stuff


    why is npm run build not pushing to mine?

    * add more info to the nodes
        * need example queries and parser (probably starts with just queries)
        * need to add arguments in and out like a function
        * this can help the llm for both
    

    * this is a good golden test suites
        * so go in and lable them better for automatic tests
        * starts with system goals
        * maybe your system goals is your plan...
            * which also just push the args parser to later
            * and it's being the system goals DAG...
        * but yeah label them, correctly
        * maybe have a build in chat id, which it does already (number)
            * need to show the chats descriptions and notes

        * make the praise and issue optional

    * There's a semaphores bug (also try lowering it and see)

    * need a better rejection (compleixity, prompt injection, and weird stuff)
        * for v1, try not to recover or buffer goals
        * just clear direct queries (maybe even no this, or that, previous one etc)
            * no follow up or continue answers
            * one query and the system can or can't finish it
            * then direct the user to follow up query with direct answers
        * just try to set up a good infrastrucutre, logging, retrieval nodes

=======================================================================
Test:
* test more concurrency and timeout (unit tests? and the semaphores?)
* add bad words to test suites and the Chronicles of Zephyrian Doombringer' series and everything by its author

Polish
* make orchestration into a workflow?
* rename your @task to @op_task or something (so no name conflicting)
* rename OperationalResult to OperationResult
* workflow self.result to self.op_result (so it's clearer)
* rename all the issues to feedback

=======================================================================

Reminder:
* don't add more frontend features, you should be reducing features
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

=======================================================================

Code review findings (security review, 2026-07-12):

New (found this review):
* app/api/routes/chat_run.py:14,26 - GET /chat_runs and GET /chat_runs/tests have no
  auth dependency, and there's no auth middleware anywhere in app/main.py. Both return
  ChatRunModel.to_dict() (db/schema/models.py) for every row unscoped - full
  user_message/assistant_message/session_id plus the planner/tasks/sse_events JSONB
  traces for every session, paginated via limit/offset. Anyone can page through the
  entire chat history of every user with a plain GET. Needs an auth check before this
  ships anywhere reachable from the internet - at minimum gate it as an internal/admin
  route.
* app/api/routes/feedback.py:34-47,50-57 - GET /feedback?chat_id= and PUT
  /feedback/reaction take caller-supplied chat_id/session_id with no ownership check
  (feedback_store.py's get_by_chat_id/upsert_reaction just query/upsert on whatever IDs
  are passed in). Docstring claims the write is "scoped to the reviewer's own
  session_id" but nothing verifies the caller actually owns it. Combined with the
  chat_runs disclosure above, both IDs are trivially harvestable, so anyone can read
  others' filed feedback or silently overwrite another reviewer's like/dislike. Lower
  severity than chat_runs (bounded to an internal review dataset) but same root cause -
  needs real session ownership verification, not just "the ID is hard to guess."

Investigated, not flagged:
* db/stores/base_store.py:19-21 - print()-logs compiled SQL with literal_binds=True on
  every query, but traced actual callers: only book_store.py routes through
  _execute_statement (book title/author/ISBN/filter search + embeddings). chat_run_store
  and feedback_store call session.execute directly and never hit this path, so no
  chat/feedback free-text or session_id actually gets printed this way. Still sloppy
  debug output worth removing/gating behind logger.debug, but not a real data-exposure
  issue as originally suspected - no PII or secrets flow through it.

=======================================================================

Test coverage gaps (new, not already in this file):
* db/stores/ - [PARTIAL 2026-07-12] utils.py now has SQL-injection regression tests
  (tests/unit/db/stores/test_utils.py). Still zero tests for book_store.py,
  chat_run_store.py, feedback_store.py, base_store.py.
* app/api/routes/ - only chat_message.py has a test; session.py, chat_run.py,
  feedback.py, health.py have none.
* app/domains/{books,project,users}/schemas/ - no tests for domain request-schema
  validators.
* common/context.py (AppContext), db/bootstrap.py, db/readiness.py - untested.

=======================================================================

Code cleanup pass (2026-07-12):

Walked the planner/request path (backend + frontend), fixed the cheap/mechanical
items already tracked above (marked [FIXED 2026-07-12]/[DONE 2026-07-12] inline),
implemented the mermaid TD/LR orientation idea, and added regression tests. Left
untouched (need real design decisions, not just cleanup): chat_run.py/feedback.py
auth, context.py ping_services, book_store.py per-author N+1 query, uuid_8 collision
risk, sse_stream.send_chars per-char streaming, FeedbackIn.message max_length. Did
not touch task_runner.py (currently disabled/removed from Orchestrator.run) or
db/ingestion/ (legacy, out of scope per CLAUDE.md). Dockerfile/local-deploy review
deferred to a separate follow-up.

[FIXED 2026-07-12] tests/unit/app/orchestration/test_orchestrator.py::TestOrchestratorRun::
test_does_not_record_when_result_is_none - was asserting the wrong layer: it mocked
record_chat_run away entirely and expected Orchestrator._finalize to independently skip
calling it when workflow.result is None, but _finalize has no such guard - it always
calls record_chat_run unconditionally, and record_chat_run's own first guard clause is
what decides not to persist. Renamed/fixed the orchestrator test to assert the
unconditional hand-off, and added test_missing_workflow_result_records_nothing to
test_run_recorder.py's TestRecordChatRun to cover the real guard behavior.