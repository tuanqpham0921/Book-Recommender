# Design decision

## @task and workflow
@task
   -> @task
        -> @task

or

@task
    -> workflow
        -> @task
        -> @task
            -> workflow
                ...

this is allowed, and it will go into steps
tho for @task I could collect just 1 envolope
ex:
    @task1
        @task2
            @task3
    could just take @task3 at the top
    or whatever the bottom is (without overwritting the time stamps)

However, this will be difficult for concurrent tasks or workflow
ex:
    @task1
        -> workflow
        -> @task
    these should just go to @task1 steps
or it will remove the trace
    @task1(args=a)
        -> @task2(args=b or something else)
----------------------------------------
So it's best for now to make it allowed
    @task
        @task
            @task
all of which go into the caller envolope
this can make it look a little weird / reduant
but it think it's a good trade off and allow the user see
how they are setting up @task,
you can prune, or re-arch, or decide where the trace should go

it should help with concurrent tasks, and debug the trace
since it could be
    @task(args=a)
        -> do something simple to args=a
        -> or complicated (sync or async) transformation
        -> @task(args=b)
you have the flexibity to see if the args changes
-----------------------------------------------------------------
so I think the analogy is like a python dict or containers
the user can technically design
{
    a: {
        b: {
            c: ...
        }
    }
}
but it might be a bad or intented design for them
or flatten it. So the record envolope is a container that's similar
but leaving it to the user to set up how the trace/stack look

-----------
@task
func1(a)
    @task
    func2(a)
        b = transform(a)

    @task
    func2(b)
        c = ...
    return func1 result
is one topology
while:
@task
func1(a)
    b = transform(a)
    @task
    func2(b)
        c = transform(b)
        return c
is also another topology (nested)
this is up to the user

--------------------------------------------------------------

## workflow vs @task

with the decision above, @task is technically a workflow
@task
    -> @task
        -> workflow
        -> @ task
for now, I'm not sure about retries and business logic retries
but @task is function based, where workflow is class base

workflow is better for organizing capability or functions together
tho it doesn't have to. Same with tasks

so keep both
--------------------------------------------------------------

## run_async_step, @task, raise on failure, Stepfailure

These concepts are not flushed.

### run_async_step
I'm not sure if run_async_step should always return an envolope?
should it be wrapped in @task?
should it return the response rather than the envolope
    * since the run_async_step already check .ok and raise
    * so should the caller get the envolope unpack it and decide?

with the design above
    you could run into the problem of
    @task
    run_async_steps
        @task
            func1

    which will then make the nested behavior thing
    it does go back to the point and analogy of nested dicts
    it's really about how to set up the trace
    so I'm not too sure yet

### .ok responsiblity
.ok is just for the producer side to determine if it had full-fill the contract
* planner - llm parsed nothing is a pydatnic validator error or an api call error
* planner - produced no tasks/goals is ok since it did what it was provided
* db query - no books is ok, since it did what the input provided
* extracting args, have no books for anchors is ok=false and raise within its business logic.

so be careful about empty response vs internal producer steps.

you don't want to have deal with a complicated ok from the producer side into the consumer. Try to keep the producer raise... on business failure.

task-runner is a aggregator, it just checks if things ran. Does not know the content.

----
so what does ok means in these cases. 
The function producing the envolope or the caller conditions
for sure, it means no run_time_error

it can be both. so the producer is saying 
"ok, and I parsed, or did my part of this work"
then the consumer unpack and decide
"let me check cycles or format and pass it to somewhere else"

but these could change how the run_async_step is returned?
tho I lean towards returning just the response
and the run_async_step is basically a layer to catch
producer side saying "not ok or run time error"
    * and if this happens then consumer can or can't continue
    * depending on raise on failure?

but the main problem with run_async_steps is the record
what if child function isn't @task or workflow
    should we make a default and be like
    "this step is not traced or documented"?
    or just document it in details
        -> "func ... is not traced"

there's also the problem of just
result = await workflow/@task(...)
    * I think this is similar to run_async_steps(..., raise on failure=True)
    * or it is false?
    * there is an .add_steps in there
    * which is different from the .add_step in context var...
but the problem is the naming convention or it's usage?
bc if it's the same as calling run_async_steps(..., raise=True)
then it might be a different thing?
    and run_async_step is more like "I want to capture the envolope, no matter if there's error or not" ?

not entirely sure how the context vars is being decoupled or intergated
--------------------------------------------------------------

## others 
* keep the record nested and seperate
    * call the flat function is cheap and easy
    * nested also helps with "sandboxing" idea
    * you don't always have to add the the parent, allowing for more flexibilty to not add or add to a different field
* for now don't try to have an llm workflow or overlap with app (as much as possible)
    * it could be useful, but I'm not too sure what is needed or other use case
    * have the app workflow for this app specific
    * and airglider can be it's own project later on...
--------------------------------------------------------------

maybe the workflow and airglider is an ecosystem(?)
if you use it then it will be in the tree / trace
so if you @task, or make a worfklow class then it will be in your tracer
if not then you can ignore things
so async or def without @task then it won't show up in the tracer

so calling run_async_steps without returning an envolope is a violation
meaning the child func is not in the ecosystem, so it won't be added to the tracer
if the user do this (intentionally or forget), then you can add details and return the actual response
    * but if child func is not in the ecosystem then, raise on failure and other mode won't be available

### Rules
    * @task will always return an envolope (for integrated or non integrated func)
    
    * @task can't receive an OperationResult as raw_output
        * it has to get the result or None

    * calling run_async_step(non integrated func) will just get the bare response, and run_time_error will crash the system
        * but it will be in details of miss-usage or a mark that this func is not in the ecosystem
        * still can return on accidental use
    
    * calling run_async_step(integrated func) will have the ability to get the envolope, inspect (useful for llm to retry and change args(?) or manual handler)?

    * calling result = await non-integrated fun/workflow(...) is a normal func calling and will crash and raise the run_time_error
        * at the current envolope run() -> return the currrent (caller -> crash) evenlope that fail here
        * if it the caller is not in the ecosystem, then it's just a normal python thing 

    * calling result = await integrated func/workflow(...) is similar to run_async_step(..., raise=False)
        * because you will always get an envolope back, and the caller will unpack it themselves (via, result.result or some other naming convention)
        * since it's in the ecosystem, without the run_async_step() it will automatically get added to the tracer
            * not sure if there's a case where we don't want this? but it makes sense this way. Not sure if it will be hard change this automation rule later.
        
    * calling result = await run_async_steps(non integrated func/workflow, raise=true/false)
        * those raise is not available for the child func/workflow(tho airglider workflow is automatically integrated)
        * will be like a normal async call.
        * but using the in ecosystem run_async_step will capture in details that this might be a miss-usage or forget to integreate the child func/workflow
    
    * calling result = await run_async_steps(integrated func/workflow, raise=true)
        * will help reduce the manual check for .ok and stops the run here
        * default for most flows
    * calling result = await run_async_steps(integrated func/workflow, raise=false)
        * will get the envolope back for handling errors
        * can be use just as result = await integrated func/workflow

so is run_async_step always returning an envolope?
    * calling on non-integrated func will record the mis-use and return the bare result
    * what if the func raise an error, which I think it will just raise it normally

    * the weird part is result = await run_async_steps(integrated func/workflow, raise=true/false)
        * if it's raise=true
            * child ok=False:
                * then you still get the envolope back, with the failure (business or run time) with ok=False
                * then StepFailure is raised
            * child ok=True:
                * then you get the envolope back,
                * then run_asyn_step return what (envolope or bare-result)?
                    * envolope is already added to the tree
        * if it's raise=False
            * child ok=False
                * then you get the envolope back, you have to return the envolope back to the caller
                * you can't return the result since there is no result?
                    * there could be result and no run_time_errors, business failure
                    * you still return the envolope back
                * StepFailure skip
            * child ok=True
                * the you also just return the envlope back or just the result?
                * return the envolope back

so with this do we want run_async_steps or it should be some other functionality
like run_bare_envolope (still some issues with mis-use and calling non integreated func)
    - maybe in ecosystem so if non intergated func will just raise as mis-use
    - rather than trying to recover and handle variant? (but then you could waste computation just to find out)
    - but that's normal for most tools tho, you might not want to make it too easy and handle it for the user
    - at least not right now
run_add_to_tracer_response(?) - return the response only (works for raise=true and non intgrated func)
                              - might have issue with okay=False no run_time_errors
                              - or run_time_errors no response
                              - or just do ok=False business or run time then this will just raise
                              - so run_async_step(..., raise=True)
                              - the business errors won't get pass back into the caller(?)
                                    - but it will be in the racer
                              - only use where continue can't happen and no retry handler(?)
=============================

from airglider import current_parent

@task
async def similarity_search(self, search_text, exclude_isbns):
    rows = await self.store.search_by_embedding(embedding)
    current_parent().add_details(f"{len(rows)} rows before isbn exclusion")
    ...

* if you want the @task to handle the record
* tho there might be some overwrite or things feature needed

=======================================================

### Rules
    * @task will always return an envolope (for integrated or non integrated func)
    
    * @task can't receive an OperationResult as raw_output
        * it has to get the result or None

    * @task can edit details using get parents()
        * tho this can come later as we need to mark the decorator not to overwrites or set things again.
    
    * .ok is for the producer to set based on execution 
        * use raise when an internal step fails
    * .ok then is unpacked or not by the consumer to handle

    * unwrap() is in the consumer side, and raise a StepFailure if ok = False

    * The producer judges completeness: did I fill in what I promised, given the input I got?
    The consumer judges sufficiency: is what I got enough for what I'm doing?
    
    * an uninstrumented task or workflow will raise or fail like a normal python function. And it will go into the caller envolope

    * the consumer will sometimes handle unwrap the envolope
        * this is for cases like triage sending a custom sse message rather than just fail
        * or check re-tryable

def unwrap(self) -> OutputT:
    """The payload, or stop the caller."""
    if self.ok:
        return self.result

    if (parent := current_parent()) is not None:
        parent.add_details(f"FAILED STEP: {self.name}")

    if self.runtime_error is None:
        # Not-ok without a crash. Under "ok = ran to completion" this cannot
        # happen, so say so here — otherwise the caller's log line reads
        # "stopped" with nothing below it explaining why.
        raise StepFailure(f"Step failed: {self.name} (no runtime error recorded)")
    raise StepFailure(f"Step failed: {self.name}")

=====================================


the raise step failure to span is like

@task
func2(a)

@task
func1(a)

    b = func2(a) <- this is an envolope, added to func1 envolope
    result = b.unwrap() <- raise StepFailure here
    
    or func1 can be handle it by it self
    if you don't move it to span then you'll see the StepFailure
    in the monitor log, because of logger.exeception in RunTime Errors

    I think stepfailure just warning say this stopped
        * whether it's workflow or task
        * since the child should raise runtime error if not ok?
        * no need to have the trace on the caller
            * espically noisy for nested worfklow/task
            * you can just see this stop, stop, stop...
        * but if you don't handle the child func raise correctly
        * then it could set ok = false, and no errors, you'll just see the caller stopped and don't know why
        * but you do or can raise the failure as "this step name failed, no runtime errors or contain run time errors"
