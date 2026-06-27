Current:
1. create a way to run all your test queries (pod mode)
2. show rejected quries and resuls
2. then a script to send all those to the frontend for you to review
3. deploy your app without DB

=======================================================================

Unit Test:
1. test your common repo utils first
    * test your prompt loader and format and such
    * make sure you can save and parse those data correctly
2. test the base request and request schemas pre-post validators
    * create fake openAI response (with ints instead of strs for example)
    * more than the limit the amount of strings
3. test your openAI clients and clients request (to payload)
4. test all your planner logic (dag, accepted, etc...)
5. test your WorkFlow and decorator last
    * focus on raising and throwing errors (logic first)
    * check your logger
6. tests all tools have docstrings at least

lower priority:
* test your sse stream (might change later, and working right now)
* test your ingestion (need to re-write to use workflow)

=======================================================================


Eval:
1. test repeated queries (find dune, and find dune)
2. add more request schemas (see how the planner do)
3. test the response of reject reasons

=======================================================================

Front End:
1. test your markdown and how it handle spacings (formatting)
    * nested bullet points was one
    * two dividers back to back? only one should show (or if there is no text before)
2. test error messages
3. test if your backend is not running or stalling

=======================================================================

Features (not in code):
* do openAI always make new lines at the end?
3. goal is to test and see the ochestration router
    actual task nodes implmentation is for later


=======================================================================
