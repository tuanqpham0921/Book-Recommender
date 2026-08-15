# TODO (scratchpad)

Durable planning lives in [/docs](../docs/README.md) — roadmap, backlog, eval strategy,
and design decisions. This file is only for in-flight scribbles that die within a
session; anything worth keeping graduates into a `docs/` file.

Migrated 2026-07-17: V1 scoping → `docs/design/node-taxonomy-v1.md` + `docs/roadmap.md`;
code-review/security findings, test gaps, workflow-framework notes → `docs/backlog.md`;
golden-test/suite notes → `docs/eval-strategy.md`. Historical cleanup logs live in git
history (`git log -p -- backend/TODO.md`).

---
continue
    * make a new branch
    * remove a lot of the implmentation from it
    * have a reference to this branch
    * and add things back in slowly with the new airglider protocol

* something to watch out for
    * RequestContext just load everything at the Orchestrator level
    * give all of it to the sub nodes (mainly I'm not too sure about the current code. Might have over done it, something I can optimize later)
    * check the preflight and compose
    * forget about tool calling! or linking the schema or multiple tools into one node
        * focus on this book rec system needs rather than PlanJane for now
        * which is nl_query -> parser -> tool call link to this executor output
        * don't try to handle the if it's already parsed right now (you kinda know what to do if that's the direction)
    * most things that need
        * llm_parse to schema
        * postprocess, validate, db query
        * return result should be a workflow or @task
            * and just link it like a 1 dimenstion schema/executor
    
* recommend node you literall just do
    * parse query = (semantic_input="...", filter="...")
        * input = "Find book like dune but darker and scary vibes"
            * parser -> semantic_input="darker and scary vibes", filters=None
        * input = "Find book like dune with 300 pages or more"
            * parser -> semantic_input=None, filters 300 pages or more
    * so the parser at the recommend node is a query decom or tool calling selector
    * build description -> workflow
    * build filter -> workflow

so try to keep it 1-1:
    pydantic_tool_schema():
        ...

    ExcutorWorkflow(natural language query)
        parser(tool_schema) -> set the toolmessage to the envolope response
        do stuff
        finalize

tho an ExecutorWorkflow can call other ExecutorWorkflow
    * similar to triage -> planJane
    ex:
        RecommendToolSchema():
            semantic: str
            filters: str

        RecommendExcutorWorkflow(natural language query)
            parser(tool_schema) -> set the toolmessage to the envolope response
            do stuff
                await AnalyzeReferenceWorkflow(nl_query=semantic_str)
                    * 1-1 mapping between a parser and the tool_schema
                    * here is where the prompts and examples can be
                    * set the result -> envolope Response
                await FilterBuilderWorkflow(nl_query=filters_str)
                    * same thing here

            unwrap both() or handle
            do the embedding search <- @task

            finalize

might be a little in-efficient but it keeps the shape we have right now
Executor(natural_lange_query)
    * analyze nodes and more complicated nodes like Triage require tool selection within it
        * triage -> select[cached_plans, clarification, small_talks,  planner,...]
        * recommend -> select[description_builder, filters]
    
    * but most tools can't call other tools
        * atomic level operations
    * communication between nodes is through natural language

we can do the parsed_args as an input later on
but the bulk of the executor will remain the same.

or you could just have the Recommend

RecommendNodeToolSchema:
    ideal_book_description: str
    filters: BookFilter

AnalyzeRecommendExecutor
    def run(nl_query, artifacts):
        artifacts = process_and_format_artifacts
        parse_args = parse(nl_query, artifacts)

        do embedding search
        finalize result

so this remains 1-1, this might need a bigger model
to summaried:
    * keep 1-1 tool and executor
        * LLM_parse set the ToolMessage to the envolope record
        * if you need another llm call, make a new workflow or a @task func for more simple op
            * @task still follow the llm_parse -> op -> toolmessage to envolope rec
    * communicate with nl_query between executors
    * a node that call other nodes should start a new workflow and unwrap
        * a node with (query, artifact) might need to process artifacts
-----------------------------------------------------------------

continue
    high priority - flush out the be more clear about
    nodes, tool schemas, executors (the nl input and a regular tool call __call__)

    * maybe a good place to start is recommend node
    * and what is a task or workflow or a normal util func

    * current implemntation is mixed between a 1-1 mapping
    of tool schemas and its executors
        * they are mostly like that but the recommendation node
        * and the concept of the executor taking in a nl query is different
            * because now to use the tool, you have to go through the exeuctor with a natural langugage query
            * you also need to know form filling llm, vs post processing form filling, vs actual tasks
        
        * like DAG in task plan, is the tool schema 1-1
            * if you have different implmentations then how does that work?
            * and does the cycle dection/processing belong to the same executors
        * then you also have recommendation node, which does multiple things
        
        * it seems like the natural language query in the domain
            is an orchestrator for this capability
            you can have multiple tools, or different tools versions
        * for now, don't try to combine nodes
            find titles have find series tools
            because your evals don't support it yet
            so just mainly do 1-1 tool and executor
            or the function calls
            and your recommendation nodes have multiple steps/tools
            so if you set that up correctly, then it will
            be similar. with swapping out tools or adding new ones


seems like there's an idempotent issue with 
run_async_step, @task and things...
    * tho it should be okay because @task idempotent?
    * because it will make a operation result or not
    * but then the timing/duration might be wrong?
    * current @task override the OperationResult returned to the decorator

you want to have the
Capability/ExcutorWorflow():
    def run(args):
        tool1
        tool2

model it off the RecomendationNode
    because you have to have a [AssistMessage=tool_call, ToolCall=result]
    and the assistant might call/query a capability
    FindByTitle is just 1 tool call so it seems off
        even if you have series, or fuzzy or something
        so the workflow output can be the ToolCall mesage

    While Planner, Triage, Recommendation are different
        Planner right now do one tool call that task1 -> task2
        but later you can have something like recommendation multistep
            entity generator tool, analyze generator tool
            link them
        but either way the output contract would be like 1 tool call
            but you need the parser and the tool_message result

    but then the output has util functions...
    if I make it into a workflow, then I'm not sure about the fields
    then you have to make sure they aren't dump into the payload...


continue:
    * don't try to do details + logging
        * logging is for starting, failed, end
        * details is for the pipeline stuff
        * you can log important stuff if needed

    * clean up the tracer and tree and stuff
        * work on the tool calls and token usages
        * make sure those are okay
        * need to move the tool call to the node
            and add the messages you get a clean convo history
            for each workflow etc...
        * maybe leave off the messages, just make sure you have a 
        list of chatmessages, I'm not too sure how previous chats will work yet
        so trying to get each workflow to work may cause refactoring later

    * stick with just the eval baseline 
        no Node([tool1, tool2, ...])
        I don't want to test it for v1, since i know or semi know
        the this way works
        but I think the idea is

        planner(query="less jane Austen", 
                artifacts=[
                    conversation_state={
                        summary="just recommend books",
                        previous_followup="would you like me look for something ..."
                    },
                    previous_rec or current books=[isbn=..., isbn=...]
                ])
        ->
        task(
            query="recommend more books without [ibsn] from previous"
            target_node = recommend
            atrifacts=[isbn13, isb13, ...]
        )

    * make a unified reference/artifact creator
        * follow the same format as mermaid
        * but it should have name, decription, and the text

    * reduce the codebase (comments and stuff)
        * mainly for claude and compact
        * update the docs for this branch
    
    * cleaning up your workflow
        * app_workflow should hold llm, tool calls, parser level
            * parser can take a generic prompt fill this schema if none are provided
            * should also take in the req and stuff?

        * for your system
            * the output should have
            input:
                natural_langage_field
                dependent_results (or artifacts or docs)?
            parsed_args:
                things needed for the output
                it could be None, single schema, or multiple schemas
            output:
                * this can return schemas (planner, books types) or natural language
            * this should be standardized for all the nodes gneration
                * you can have a generic prompt
                * or pass in a custom prompt, models, ects...
                * and the parsed_args and output just do to_summary() -> response

        * you might not need node_workflow
            * since a lot of that is for the app_workflow
            * and the you can put common useable functions
                * format artifacts,
                * generate a response
                * ui_colapsable (so parse intent isn't not showable(?))
        * remove the generation node attached

    * you might not need the parse_intent(?)
        * the planner main is an executor to keep it the same shape?
        * parsed_intent is a goal setter
            * and it could just be a utils like refernce analyze? or you want it to be a workflow as well
        * even the planner can take it dependent results or artifacts context. so you can pick up or continue
            * but for now if it's there just log

    so i imagine the op result to be like
    OperationResult
        id: 
        ok:
        # not sure about this it can be large
        # the caller should already know
        input: ... (new and it can be dict or some type)
                   (for our arch specifically, this is where you can have:
                        query=...
                        dependent_results=... (or artifacts or context)
                   )
        steps = [
            do what ever it needs in here
        ]
        output = ... same as before
                     but for this app nodes
                     it should return:
                     sometype:
                        parsed_args= some type to call .to_summary()
                        output = sometype? or call result?



    ----------
    
    * set up the filter node that recommend can call independetly
    * add in genre node so you know that the query builder work
        * should be (title + genre) -> filter -> recommend - output
                                                    ^
                                                    |
                                                    V
                                                    filter
    * format the sse events more clearly for UI
    * then look at the arch and set things up more correctly
        * re-usable functions, workflow / internal schemas
    * add a answer to the planner field
        * might go back to system with the extended to eval for sure

TODO:
    * re-name and re-define analyze recommend node to something better
        * it should be like recommend based on references (book or analyze docs)

    * have the db or book domain caller load in the book model
        * summary is a function that return a book summary thing?
    * book store should hold sessions factories
        * each query is a session
        * so it doesn't just 1 session for a query
    * create a compact mode tracer that filter out fields
        * or even flattern the tree
        * it can store only things like isbn and title
        * no need for parse_arguments, and such
    * add a add_details(msg, log=true)
        * not sure what should get monitor and log yet
    * ~~might need to remove message in operation result all together~~ DONE 2026-08-07
        * it's just noise and extra overhead
            * details should contain the buffer messages
        * gone from OperationResult, and with it success_message/failure_message
          on every workflow and the message= arg on finalize_result
        * failure text now reads off runtime_error.message (which the review
          page and report.py actually consume)

cuurent issue
    * the retrieval title Brave new World is not catching
        * because the DB have Brave New World .. revisited
        * might need to clean db books or add a new field or just add a regular book
        * or might need to change the actual query to use ILIKE...

Ideas:
    * send the reference books isbn13 to the recommendation somehow
        * or the query
        * so you can have a why? button that will query the compare_node directly
        * and just compare them for you, without having to call the planner
        * this will need just the isbn13, it can cost a little bit to go to db again
            * but caching and stuff can come later

    * possible to have the db query to have multiple calls in one
    * so instead of 50-100 pages, we can do 3 different ones at the same time

    * you could just expose the analyze nodes / action nodes
        * compare, recommend, single book analysis (for q/a)
        * then each of these can then call / query the planner themselves
            * and it could have like book retrieval marker for example
            * and the planner will only load in the query builder and search
        * but this is for later, since you just need to know dependencies between analyze node
        * tho it can cost a lot more
            * recommend similar to book1 and book2, then compare book1 and book2
            * which will be recommend(b1, b2), compare(b1, b2) where
            * each call the planner seperately. you can cache and stuff but race conditions
            * this is where entity classifier can help, for caching and re-using them


    * or for multi-turn, you could have
        previous_convo = original_use_msg
        try:
            while true:
                planner = ... (prompt: here are the capabilities, get 10 goals at a time)
                task runner = ...
                reword = ...
                previous_convo = reword
        final:
            internal_summary = "recommend book isbn13, the user wanted to pause..."
        
        this way you are looping but in a control way
        so like you can only do 10 steps in one loop for example
        have the retrieval isbn13 and recommended books for continuation

    * you might need a natural language field the data stuff
        * so like "for this operation, it took me 10 seconds, using this amount of tokens"
        * or I look at similar search db with {...}, and applied filter{...}
        * not sure if this is needed tho, it could help with generation and passing in stuff
        * might just be a function call and make as you go.

Performance Ideas
    * you can have pre-made graphs common ones are
        * find title -> recommend
        * find ... -> recommend
        * recommend me something (simple queries)
    * not sure how to speed up the recommendation part tho
        * because you don't have a lot of data
        * so you need to analyze the docs and search

FOT:
    * how would I do something like 
        "compare Dune and It, recommend me books based which is longer/newer"
            * these I can do, I just label the docs as meta-data or semantic analyze
                * pass this as a document, and the orginal user query
                * and semantic stuff is for description builder
                * and filter docs are for the meta data filter parser
        "compare Dune and It, recommend me something longer with 300 pages or less"
        
        * these are loop / agentic archtecture is much easier
        * because you just go to compare re-write then go to recommendation next
        * for the planner to work you'll need it to have
            * recommend(query="some marker saying waiting on compare it and dune and recommend which ever is longer with less than 300 pages")
            * then you have to process that and either ask for input
        * wait this should work
            * if the doc return "Dune is longer than It by 100 pages. So it wins the page comparision with It"
            * then you just embed and find with the filter.
            * you can have different analyze documents
                answer = ...
                winner = [book1...]
        * you can't do themes based comparision or semantic comparisions
            like "comapre which is better on dystopia or magic abilities"
            you can only compare on metadata for now

        * this should be okay as long as a node doesn't go node more than 1 away
            * so you can't have

                                this edge should be prune 
                                (since it's already processed)
            find[dune] ---V ------------------------V
                          analyze[dune, it] -> recommend[...]
            find[it] -----^
            * not sure if there's a case of this

        * there are 2 types of compare
            1. just for general info (between dune and it which is longer)
            2. to get a winner (recommend books similar to Dune and It on which one is shorter)
                * recommend can only that this?
                * it won't take the first since we're just doing meta data filter for now
---
currently
    * get the recommend (a collect node) set up
        * the collect node always have to make sure it's not too many
        * and it's returning a list of books
    * then design an SSE stream events for the UI
        * things like sections and message and stuff
    
reminder:
    * put in the out of scope that you can't answer things not in the db columns
        * so like who's the main character of the Hunger games?
        * or that guy with the sword in Dune
        * but you can answer things like Who Dune was written by or when...

initial re-tries design
    * The workflow holds the retries
    * right now everything is 1 pass
    * but if you want retries (business logic or re-write query)
    * you'll have to wrap the hold workflow and each
        * llm_args_parse -> post_process -> store to an output
        * and this whole thing is in a seperate operation result
        * this is similar to how the llm api is returned
    * the current only retries on api or calls errors
    * the parent handles the re-write and business logic
    * note for your arch, the hitl is only for filtering or determinisitic options
        * you can't do free input yet, because it's a lot more. They can put, actually compare instead of recommend
        * this will need a cut off re-plan (remove this node) or complete re-plan
    * it's human in the loop, but you don't have a loop
        * the only hitl is at the analyze nodes
        * you they want recommend books between 1990 and 2000 or compare, there could be thousands of books to embedings for similarity search
        * this is the place for it
        *retrieval hitl or retries are hints, if you can't find exact match
            * it might be a confirmation that the fuzzy search or the llm parser
            * prior knowledge is suffcient, if not then you can discard the books for the next step.


* make each task returning a output type (instead of the sse_stream)
* then at the end is where you want to do the generation
* think about your UI and how it should work
    * generation vs references...
* migrate to v1/responses

Goal for now
    * getting a set up just for find_title and recommend

current eval issue
    * why is parse confidence 0.0 sometimes
    * find published year should catch "Find books between 300 and 500 pages published after 2015."
        * probably because it's not in the docstring
    * add prompt example for analyze -> recommend or the other way
        * you do best effort at the nodes
        * like for analyze recommend call an analyze node if needed
            * or compare(a,b) if no analyze(a) and anlyze(b)
            * then this could best effort to find
            * but this can be for later 

continue with the generation node
    * you need to get all the analyze nodes too?
    * or just the last node hold all the information needed to send to generation
        * probably just the last node
        * because if you have compare -> recommend -> generation
            * then it can have the reasoning in the output
            * but if you have recommend -> compare then you do want 
              the recommend output...
              maybe something like

        find -> recommend -> output
                  |         ^
                  V         |
                compare -----
    * you might need the parser
        * you don't have to pre-compute it (or you should)
        * because you do want a title and what is it answering
            * like Did Jane Austen write Dune?
            * if you return empty from combine interect
            * then it's not going to be able to capture the reason for
                find Dune
                            combine -> answer
                Jane Austen

-------------------------------------------------------------------
seems like split up system goals as planner works
    * tho there are some blurry issues
    * the findings is that recommend analyze semantic and find by genre is blurry
    * there can be duplicates tasks (not often)
    * the good side of this is that you can run the parser seperately
        * this means different prompts, examples, and model
        * for something harder, like analyze recommend
            * you can use a bigger model or more reasoning and example
        * where in the old way, it's just one classifier
    * but this is now also the problem with the system goals planner
        * because it has more choices to link
            * where the old one you filtered it out already
            * so that's why the older way can use a smaller model and link okay
    * overal I do think which ever way I decide to do
        * these are about as good as it gets before I need very intensive eval
        * it does seems like the description as query normalization work
        * and there are just more optimizations
            * things like book domain, project domain, or user domain
            * this can filter out some stuff
                * then you can filter out deeper like no actions and such
            * I don't think it's the main issue tho
            * linkage and goals setting seems okay
        

current
* add a parse arguments of the normalized query fields
    * see how it does first
        * in one request or as seperate in task_runner
        * parsing seperate means less chance of hallucination
            * and better agentic feel (since you can do pending)
            * but it means more api calls
            * seems like the cap is at 500rpm (if you have 15 requests)
                * that's 15 parsers, so you can have around 33 users at most in one
                * tho it varies due to the step nature
                * the next tier is 5,000rpm so you should be fine
            * you also save tokens if a previous step fail before
                * you get here and parse or just not parse

polishing/nice to have:
* have the reasoning answer in first person ("I need to find this title first...")
    * tho if you use the reasoning for reparse it could be a problem

current added intersect and filter retrievals
    * why this way is that at each step
    * i can do a cte to ensure that there are books (candidates)
        * if none or too many then I can ask the user
    * and why seperate the filter is that you can explitcit
    inject human in the loop at that step knowing the previous
    ctes have all the books still. you can constrainst or relax
    the query from the user easier(?)
    * also with intersect, if there are none then
    you know there are no books with that criteria
        * no need to relax of constrainst there
    * same with read books, you can exclude it
    and if there are none then you know they read all
    the books in those criterias like by this or something
    * the problem is you can't go back
        so filter1 -> 
                      intersect
           filter2 ->   
        then you can't change those other filters
        which can be a problem or what you exepect for
        this?
        so maybe for v1 you only want human in the loop
        at the end? for recommend
        if there are none on the other ones, then you 
        can just stop the query?

    * with this split i can do things like
        * my database has 500 sci-fi, I have also 10 books by Jane Austen
        * ui_loading: checking how many books have 200 pages or more