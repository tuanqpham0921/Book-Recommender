# TODO (scratchpad)

Durable planning lives in [/docs](../docs/README.md) — roadmap, backlog, eval strategy,
and design decisions. This file is only for in-flight scribbles that die within a
session; anything worth keeping graduates into a `docs/` file.

Migrated 2026-07-17: V1 scoping → `docs/design/node-taxonomy-v1.md` + `docs/roadmap.md`;
code-review/security findings, test gaps, workflow-framework notes → `docs/backlog.md`;
golden-test/suite notes → `docs/eval-strategy.md`. Historical cleanup logs live in git
history (`git log -p -- backend/TODO.md`).

---
currently
    * set up a preplanner that you can load in or mock
        * Show me books similar to Pride and Prejudice
        * Find books like 1984 or Brave New World
        * Find books like 1984 or Brave New World, Dune, Brave New World (for more than 5)

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