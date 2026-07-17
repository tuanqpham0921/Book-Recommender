it might be hard to get all the queries
* maybe I should have the parse intent just reject on weird and ambgious qeuries. and just do like "please be more specific"
* this can help filter out weird stuff (like do it again in reverse)
* maybe the args parser is not needed?
    * maybe the nodes can handle the args parse?
    * it will be the same token count ish?
* seem like I should start with the system goals check
* need a tool capabilities nodes

========================================================
add tests:
Show me all the books in the 'Chronicles of Zephyrian Doombringer' series and everything by its author
* without the author name (there's a test with one already)
* test to see the pending or if it will move over
Queries with bad words or books with bad words
* Subtle Art of not Giving a Fuck
* and just general things

===================================================

overal, not too bad
* can't tell if scaling works or it confuses the llm more
    * not sure if it's a smarter node (or conflicting node) things
    * unclear direction/prompt, model, tempaerature thing
    * or I haven't review the extended nodes thing
* better examples in the nodes (query and parser)
    * since it's a scaling test i'm not sure about other nodes
* problem is once the plan is made, it will be hard to edit or fix
    * where a router can be more deterministric
    * maybe we can have a score (missing goals, and confidence for the parser)
    * if the score is low then pass it in to the llm to review/fix
        * but there is case of missing tasks for system goals that can be pipe back to the argument parsers
    * so trying to generate the full plan at once is optimistic
* maybe I should have a commplexity or confushing score for the initial parse
    * and just reject aggressively rather than trying to recover

Trade off ot FOT:
    * more LLM passing - more tokens 
        * probably slower but more accurate
    * should I get 3 steps planner back?
        * arg parse then link
    * should I delay the args parse to the nodes?
        * this way it's the same as one big one with extra metadata
    * for this version, maybe I should just roll with this design
        * and hope for a good plan...
        * since I really don't know what kind of queries or how it will perform...
    * definitely needs a project tools catalog, and better rejection
        at the initial parse.
    * How do I do regression tests...? would be nice to see
        what changes but then we don't want to keep adding features
        maybe just a backend script for a report generation is fine for now
        try to do no more frontend features
            * removing features/capabilities is fine

continue:
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
    * maybe remove all session feedback page
        * have a better feedback page (show the system goals)
        * probably just search by session id
        * always show the system goals first
        * make the praise and issue optional
    * There's a semaphores bug (also try lowering it and see)
    * need a better rejection (compleixity, prompt injection, and weird stuff)
        * for v1, try not to recover or buffer goals
        * just clear direct queries (maybe even no this, or that, previous one etc)
            * no follow up or continue answers
            * one query and the system can or can't finish it
            * then direct the user to follow up query with direct answers
        * just try to set up a good infrastrucutre, logging, retrieval nodes