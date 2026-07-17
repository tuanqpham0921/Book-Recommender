* need a single book analyze node
* just for retrieval like "what is Dune"?
    * maybe we don't since it's v1 and the description is there already
    * save from implmentations

Overal
* not too bad
* it could use more nodes
* maybe the planner idea is not the best
    * most queries are just like "find books in the 90s ..."
    * simple and basic queries are fine
    * for larger planner queries is very unusal for real book recommender
* there is a blur lines between find by traits and recommend node

* I probably should focus on retrieval only first
    * and the analyze node should only be LLM reponse generation
    * and this project seems more heavily on retrieval and making sure it's okay

* the planner does help to debug and see the overal plan
    * there are fields that needs previous ones and modify the current args
    * maybe I could make it have a pending instead of straight parsing
        * might be rare and I need more user data to tailor it

* it does seems like step by steps reasoning is better
    * with the current implmentation of work flow and planner it's not too bad to change
    * the only problem is how to load in the next set of tools
    * it will definitely use more tokens
    * so I would have to do 
        layer1 -> sumarize/need next steps -> parse_intent -> layer2 -> sumarize ...
    * or basically loop it back to it

* for v1, maybe as long as it runs without runtime error
    * just generate a plan upfront, even if it's not the best
    * logs and stuff, it should be okay

* Good no runtime errors and is able to capture things

============================================================
Took me over an hour to review this
branch:  test_orchestration_and_workflow
version: c8e28a6e7d43d3b0f180feb0f0071a3a0fb92946
    * mainly have legacy nodes from pre-release
    * probably need to re-arch it later

also had claude review "claude_e7d41c02"
* no need to re-arch 
* it points out that the planner does well enough
* it also agree that step by step can cost more
* suggested to do some pending or fixes

date 7/13

* need to add tests or show catalog
    * both for parse intent and what passed in strategyclassification
* need to load claude review into the review page
* get all the sessions
    * future reference, I maybe I should have a name fields

