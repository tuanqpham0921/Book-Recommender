# TODO (scratchpad)

Durable planning lives in [/docs](../docs/README.md) — roadmap, backlog, eval strategy,
and design decisions. This file is only for in-flight scribbles that die within a
session; anything worth keeping graduates into a `docs/` file.

Migrated 2026-07-17: V1 scoping → `docs/design/node-taxonomy-v1.md` + `docs/roadmap.md`;
code-review/security findings, test gaps, workflow-framework notes → `docs/backlog.md`;
golden-test/suite notes → `docs/eval-strategy.md`. Historical cleanup logs live in git
history (`git log -p -- backend/TODO.md`).

---

(nothing in flight)
* maybe you'll need an entity thing
    * group them by books or reference books etc...
* example mismatch for system goals
    * might better to have the llm_id and id switch
    * to internal id vs id
    * or you can go in an enumerate them 

decisions:
1. models mini vs nano and effort
    * or a bigger model (both cost more money and more tokens)
    * or you can see that the mini is good enough
        * and best effort inject them
        * or resolve them after (i do like this)
            * might be a good blend between intent and goals...
            * because you need the intent to know which one to clamps

    * or it's something with the parse intent
        * this becomes a massive if statement
        * I do like the system goals
        * bc if you do book reference/entity
            then you are also just linking the intent to reference/entity


---------
seems like book entity is a feasiable solution
    * it initially seems faster, use a smaller model
    * does things reasonably well
    * it also reduce tokens, as you just have 1 databse request schema
    * I could run multiple identifiers concrurrently
    * but the prompt and examples are very specific to the database
    * with a big field, it's hard to have case by case
        * but it might not be a big problem...
        * like get books with 100-200 pages, fiction. so you have to make sure there's no authors or provide example. or run the risk of it filling things
    * another downside to the entity apporach is that
        * I'm going to have to pass that whole thing in to link or something
        * which is not ideal for caching, and varies. or link it with the intents

* my current approach find by title and other things they are basically entity
    * in more granular and constrainst based on capablities
    * it's also a little more deterministic and a little clearer for the llm
    * what the system can do? like if I don't have pulished year implemented
    * it's not there. and with the entity apporach
        * I can remove the field, but it means updating system prompt and examples
        * and testing the overal BookEntity node eval again
    * I think the current appoarch is fine, I need to reword the names and such
    * adding new fields is also easier and the system prompt remains overal generic. Which is a trade off I'll keep for this version
        * since I want to build something I can re-use later and stuff

    * also my analyze nodes are intents
        * so if I was going to do book entity route
        * then I'll need an intent indentifier and link them.
        * like intent to compare_books(entity[book1, book2, ...])
        * which is kinda some the same thing (so avoid re-arch just to find out)

finding today
* the verbose docstring is worth it
    * the full pydantic model will cost like 1k more tokens per node
* the prompt injection/preflight parse is not well designed or tested
    * need to test it seperately before adding nodes
    * more important in nodes not in the planner
* re-running tests without prompt injection node
    * need to look at the system goals and the "book entity" more in this test
    * I'm not exactly sure why I'm experimenting with book entity today
        * or what prolem I'm trying to solve
* the system goals doubles as a tool selector and a re-writting of the qeury
    * instead of in_domain_msg, or intent portion of the query, lets say for compare or whatever
    * then parse the args. that description seems like a re-write portion of the user query for the parser too. which can be a good thing
    * and if the goals and tasks are 1-1, and i have goals dependencies
        * then I can run all the parser seperately
* recommend node needs to be smarter (with things like max pages and min pages etcs...)
    * which is different from refrence book query with (min/max/...)

* do I need to enums the goals?
    * did I optimize and remove the planner (edges linking seperation) too early?

FOT:
* I might not need depends_on in the parser
* since the goals nodes already have 1 single node_type for it
* it might be better to have a bigger model link the depends_on for me
    * tho this can be a slippery slope since it will need reasoning fields
    * and more completion? maybe not too bad
    * but the dependecy completition field isn't alot of tokens
* and the args parser just link task to goal 1-1, and that will have the dependency for me
* I could have the retrievals have intents or purpose in it
    * for reference, for information, ects... or just have an overal thing
    * look at "Did Jane Austen write Dune?" and goal Retrieve_by_Title
Find Dune by Jane Austen to verify authorship

------------------------------------------------------------

for v1, let's just use the current capability model
* it does seem to work with extended included
* it's also decently fast
* without the extended it will be even lowered in cost
* the entity and intent extraction is definitely a better move
    * cost is much lower, can use a smaller model
    * less decision and task for the LLM
    * can run in parrallel
    * reserve the heavy linking with the bigger model
* I can split up the entity and make it generic as well
    * but it will become similar to how i currently have it
    * so i could split the current one into retrieval task goals and intent goals
        * then link
* but for now, lets see how far having 1 frontier model at the front
    * to plan and map for me do
    * and I can experiement on embedding searches and executors
    * then for v2, I can try to optimize and reduce cost