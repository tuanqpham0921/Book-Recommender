# TODO (scratchpad)

Durable planning lives in [/docs](../docs/README.md) — roadmap, backlog, eval strategy,
and design decisions. This file is only for in-flight scribbles that die within a
session; anything worth keeping graduates into a `docs/` file.

Migrated 2026-07-17: V1 scoping → `docs/design/node-taxonomy-v1.md` + `docs/roadmap.md`;
code-review/security findings, test gaps, workflow-framework notes → `docs/backlog.md`;
golden-test/suite notes → `docs/eval-strategy.md`. Historical cleanup logs live in git
history (`git log -p -- backend/TODO.md`).

---

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