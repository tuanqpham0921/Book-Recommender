Continue:
* review code changes from 7ad4a4feb0ccfba0e64e88793aaa99791e18b0c9
    * where you started adding chat_runs and mermaid reformatting
    * where are my chatmessages?
    * why is there a orchestration column now?

* a way to load in all your test suites results
    * think sequential for click left and right
* think about your columns and how to handle it better
    * maybe try adding more schemas

* there's something wrong with how you overwrite the self.result messages
    * figure out where the put in details vs message
    * maybe push it to details with "prev message: ..."
    * change your app/workflow to not overwrite and make sure tests passes 

=======================================================================

Note:
* currently your workflow and operation is fine
    * it could be better but we can deal it more stuff later
    * right now it supports run_async_step (need a @task for non failure)
    * steps also has to be OperationalResult in add step to help detect that

=======================================================================

Reminder:
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

Eval and deployment testing:
1. create a way to run all your test queries (prod mode)
2. show rejected quries and resuls
2. then a script to send all those to the frontend for you to review
3. deploy your app without DB
=======================================================================

lower priority:
* test your sse stream (might change later, and working right now)
* test your ingestion (need to re-write to use workflow)

=======================================================================


Eval:
1. test repeated queries (find dune, and find dune)
2. add more request schemas (see how the planner do)
3. test the response of reject reasons

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