# Planner Review — session `test_2ca761aa` (50 runs)

Reviewer: Claude (feedback session `claude_e7d41c02`)
Reviewed: 2026-07-13
Scope: planner output only (parse_intent + strategy_classification), per request.
sse_events ignored. Branch `test_orchestration_and_workflow`, cross-checked
against your 89 feedback rows in session `dev_f5a12966` and
`personal_review_notes.txt`.

---

## Headline verdict

I agree with your overall read: **solid v1**. 50/50 runs `ok=true`, no runtime
errors, and the plans are structurally sound — the DAG machinery (dedupe,
topo-sort, cascade refusal, cycle detection) worked every time it was
exercised. The problems are concentrated in three places:

1. **Silent plan shrinkage** — goals/subtasks disappear without a trace the
   user (or the logs) can see. (runs 18, 36, 37, 49)
2. **Capability blindness in the parse prompt** — the catalog docstrings
   don't mention the fields that exist, so in-scope requests get misrouted.
   (runs 10, 29)
3. **Filter semantics landmines** — plans encode filters that the current
   store would execute *wrongly or oppositely* once TaskRunner is wired up.
   (runs 06, 33, 39, 42)

Items 1–2 you mostly caught. Item 3 you partially caught (you praised the
exclusion capture — the capture *is* good; the execution path is the trap).

### Usage stats

| Node type | goals | tasks |
|---|---|---|
| Retrieve_by_Title | 38 | 42 |
| Analyze_Recommend | 18 | 18 |
| Retrieve_by_Traits | 15 | 15 |
| Analyze_Compare | 10 | 10 |
| Retrieve_Developer_Info | 5 | 5 |
| Retrieve_Project_Info | 3 | 3 |
| Retrieve_User_Info | 3 | 3 |
| Retrieve_by_ISBN13 | 2 | 2 |

Refusals were rare and always at the right layer: 1 refused goal (run 41,
correct), 1 refused task (run 36, correct rule, wrong outcome — see below).

---

## Answers to your open questions

### 1. `chat_c8ad2cf6` — "did the LLM not make it, or did my algo filter it out?" (fb_ca9696c7)

**The LLM never emitted it.** I inspected the raw classification tool call:
`strategies` contains exactly one entry (the Retrieve_Developer_Info task) and
both `_invalid_strategies` and `_overflow_strategies` are empty. Goal
`goal_47bf8098` ("books about the technologies used to build this app",
conf 0.8) was accepted by parse, handed to classification, and the LLM just
didn't produce a task for it. Your filter code is innocent.

The deeper issue: nothing in `_create_dag` checks the reverse mapping. Tasks
are validated against goals (`_get_candidates` refuses tasks pointing at
unknown goals), but **an accepted goal with zero covering tasks vanishes
silently** — no log line, no refused entry, nothing in the mermaid. That's why
you couldn't tell from the logs. See improvement #1.

### 2. `chat_c5454969` — "Maybe I don't have github in the field?" (fb_9211e717)

You *do* have it: `ProjectInfoField` has `PROJECT_GITHUB_URL`,
`PROJECT_GITHUB_REPO_NAME`, `PROJECT_GITHUB_REPO_URL`. The problem is the
parse LLM never sees the field list — the catalog only shows the class
docstring ("request information about the app, tech stack, architecture, or
project metadata"), so "GitHub repo" didn't pattern-match and went
out_of_scope. Same root cause as #3.

### 3. `chat_73c20098` — token count "I think it's the prompts" (fb_1abb3d77)

Confirmed, and your hypothesis is right. `UserInfoEnum.TOKEN_USAGE` exists and
run 47 (`chat_cdf19ceb`) proves the routing *can* work — the difference is run
47's message said "Show me my token usage" alongside other explicit asks,
while run 10's bare "How many tokens have I used so far?" fell to small_talk.
The docstring the LLM sees is just "Get user information from the database." —
it never mentions token usage, memory, or conversation history. Enumerating
fields in the docstrings should fix both #2 and #3.

### 4. `chat_09bbf318` — "maybe the LLM infers Dune's pages from outside knowledge" (fb_48452a50)

Close, but it's your own config: `max_pages: 300` is `BookGuides.MEDIUM_BOOK`
("between 150 and 300 pages") and `min_year: 2016` is `RECENT_YEAR` ("after
2016"). The classification prompt injects BookGuides, and the LLM maps
"shorter" and "more recent" to the guide buckets — *absolute* buckets, not
relative-to-Dune. So the behavior is deterministic-ish and explainable, but it
confirms your "pending args" instinct: constraints relative to a retrieved
book can't be resolved at plan time. (Dune is ~600–900 pages; "shorter than
Dune" ≠ "under 300".)

### 5. "highly rated is at 4.0, so that could be a problem" (fb_c617ec7c)

Also BookGuides: `RATING_GOOD = "between 4.0 and 4.5"`. Run 15 used 4.5
("highest rated" → RATING_EXCELLENT), runs 27/30 used 4.0. The LLM is
following your guides consistently; if 4.0 is too lax, tune the guide, not the
prompt.

### 6. "maybe don't do the limit 3" (fb_fab56eaa)

`limit: 3` is `BookConstraints.default_limit` echoed by the LLM, and run 34
correctly honored "top 5". This one is config, not model behavior. If you want
the executor to own the default, drop `limit` from the LLM-visible schema.

---

## Findings you didn't flag

### F1 (high) — Exclusion filters are never applied, and the planner echoes excluded values into the *include* fields

Two stacked defects:

- **Store side:** `apply_book_filters` (`db/stores/utils.py`) never reads
  `filters.exclusion` — no code path applies it. `ExclusionBookFilter` is
  schema-only today.
- **Planner side:** in every run with an exclusion (33, 39, 42), the LLM also
  put the excluded values in the *positive* fields. Run 39 is the worst:
  `categories: ["fantasy", "science fiction", "romance"]` AND
  `exclusion.categories: [same three]` for a user who said "no sci-fi, no
  fantasy, no romance". Since exclusion is ignored and positive categories are
  OR'd into the WHERE clause, this plan would return **only** the genres the
  user rejected, sorted toward the author they excluded.

You praised runs 33/42 for capturing the exclusion (fb_711644bc) — the
*capture* is genuinely good; the execution semantics are the trap. This
doesn't bite yet because TaskRunner is mocked, which is exactly why it's worth
fixing before wiring it up.

### F2 (high) — Silent half-fulfillment via refusal cascade (run 36, `chat_4c630fce`)

"Compare 1984 and Brave New World, then recommend something similar to
whichever is darker." The LLM emitted the recommend step but **mislabeled it
`Analyze_Compare`** with a single dependency (the real compare task) — and
`CompareStrategy`'s two-dependency rule correctly refused it. Net effect: the
"then recommend" half of the request evaporated. The refusal is recorded in
the planner JSON, but the user just gets a plan that ignores half their ask.
Same surfacing gap as the run-37 goal drop: refusals/uncovered goals never
reach the user response or the mermaid.

### F3 (medium) — `keywords` are ANDed across entries in the store

Run 06 ("something spooky") produced
`keywords: ["haunted", "supernatural", "horror", "ghost", "spooky"]`.
`apply_book_filters` appends one condition per keyword and ANDs them all — a
book must match *all five* somewhere in title/authors/description. That's
near-guaranteed zero results. Keywords from one intent should OR (or feed the
embedding search instead).

### F4 (medium) — small_talk is being used as an "unhandled" dumping ground

- Run 10: an actionable, in-scope request (token count) landed in small_talk.
- Run 49: the **entire message** ("look up my previous conversations, then
  recommend...") was placed in small_talk *while also* generating a
  Retrieve_User_Info goal from it — and the recommend goal was lost (you
  caught the missing recommend: fb_21f1ce57/fb_f6c75b79).

Run 09 shows the intended use working ("This app is amazing..." → small_talk,
no goals). The schema description ("Small talk in the request") is too loose;
the field needs a "only greetings/pleasantries, never requests" contract.

### F5 (medium) — Unsupported-action handling is inconsistent (runs 41 vs 50)

`FeedbackRequest` exists in code but isn't in `NODE_TYPE_TO_CLS`, so it's not
in the catalog — yet `Provide_Feedback` **is** a member of `NodeTypeEnum`,
which means it leaks into the `SystemGoal.target_node_type` JSON schema enum.
Result: the parse LLM can see the enum value but has no description for it.

- Run 41 emitted `Provide_Feedback` → refused with a traceable reason. Good.
- Run 50 shoehorned the same intent into `Retrieve_Developer_Info(field=["bio"])`
  with description "Send feedback to developer..." — silently wrong (your
  fb_5d24a261 caught this).

Either register a stub Feedback node or exclude unimplemented enum members
from the schema, so this fails one way, consistently.

### F6 (low) — Corpus bounds echoed as filter noise

Runs 06, 13, 25, 30 etc. copy `BookConstraints` verbatim into filters
(`min_year: 1876, max_year: 2019, max_pages: 3342, min_pages: 4,
min_rating: 0.0, max_rating: 5.0`). Harmless at query time (they exclude
nothing), but they obscure user intent when reviewing plans — you can't tell
"user asked for pre-2019" from "LLM echoed the corpus bound". The prompt
should say bounds are context, not values to emit.

### F7 (low) — Spurious dependency (run 45, `chat_0cb2aa19`)

"Recommend a sci-fi book" got `depends_on: [Retrieve_Project_Info task]` —
the two asks are unrelated, and the false edge serializes what could run
concurrently. (Run 47's similar edge is defensible — books about the tech
stack genuinely need the tech stack.) A cheap validity heuristic: an
Analyze task should only depend on tasks whose goals it shares, else warn.

### F8 (fixed during review) — Capability catalog printed every retrieval node twice

`format_node_type_catalog` had `listed = set(ANALYZE_CLASSES)`, so the
"Other supported actions" fallback re-listed all six retrieval classes in
every parse prompt — token waste plus "two different capabilities" ambiguity.
Fixed in `app/registry.py` (one-line), pinned by a new test in
`tests/unit/app/domains/test_registry.py`
(`test_catalog_lists_every_node_type_exactly_once`).

---

## Where I agree with your notes, with evidence

- **Traits vs Recommend blur** (fb_afb25d60, notes): confirmed. Run 03
  ("recommend me a mystery book") produced Retrieve_by_Traits *and*
  Analyze_Recommend carrying **identical copies of the same filters** — the
  recommend node re-declares the retrieval's job. Your redesign instinct
  (retrieval-first; analyze = LLM response generation over retrieved
  candidates, no filters of its own) matches what the data shows. Removing
  `filters` from `RecommendationStrategy` would erase most of the blur.
- **Compare/recommend piping** (fb_550ff751, fb_6dd705a8): partially present
  already — runs 44, 46, 48 correctly pipe compare → recommend, and run 50's
  recommend depends on compare + user_info. The inconsistency is that
  `reference_books` re-enters titles as strings even when the retrieval tasks
  are dependencies, so the same information travels two paths.
- **Missing recommend goal on ISBN-similarity** (fb_f0b65d89, run 18): parse
  under-decomposition. The prompt's decomposition example only covers "books
  like <title>"; "similar to ISBN X" and run 49's "based on my conversations,
  recommend" don't match the pattern and lose the Analyze goal. One or two
  more examples should fix it.
- **Args parser quality** (many 👍 rows): agree. Strict bounds are right
  (`<200 pages` → `max_pages: 199`, `>4` → `min_rating: 4.01`, `>300` →
  `min_pages: 301`), title extraction handles "The Lion, the Witch and the
  Wardrobe", multi-title decomposition is clean up to 4 books, and shared
  retrievals are correctly merged across goals (runs 17, 40, 46, 48, 50 —
  `_remove_duplicates` + `_merge_target_goal` doing their job).
- **Planner-as-debugging-artifact**: strongly agree — this entire review was
  possible only because the plans are recorded. Whatever you re-architect,
  keep the recorded plan.
- **"For v1, as long as it runs without runtime error"**: met. 50/50.

### Where I'd push back gently

- **"maybe the planner idea is not the best... most queries are simple"**
  (notes): the data half-supports this — 27 of 50 runs are single-task or
  trivial two-task plans where preplanning adds two LLM calls of latency for
  no branching value. But the 10+ multi-goal runs (36, 43, 44, 46, 48, 50)
  are exactly where the planner shines and where your users' compound queries
  will live. Rather than abandoning preplanning for step-by-step reasoning
  (your notes' layer1→summarize→layer2 loop — significantly more tokens and
  latency), I'd keep upfront planning and add a *single* cheap repair pass:
  if coverage validation finds an uncovered goal, re-ask classification once
  with the gap named. That gets most of the iterative benefit at ~1 extra
  call only when something is actually wrong. Your "for v1, generate a plan
  upfront even if imperfect" instinct is the right call — the failures above
  are validation gaps, not planning-paradigm failures.
- **"need a single book analyze node"** (notes): agreed long-term, but note
  your own v1 counterpoint is validated by run 01: "What is Dune?" →
  retrieval-only plan is fine because the card carries the description. I'd
  rank it below the coverage/exclusion fixes.

---

## Run-level annotations (only runs with findings)

| Run | chat_id | Finding |
|---|---|---|
| 03 | chat_88db60de | Traits/Recommend blur; identical filters duplicated in both tasks |
| 06 | chat_39d2c062 | 5 ANDed keywords → likely zero results (F3); corpus-bounds echo (F6) |
| 10 | chat_73c20098 | In-scope token-usage ask misrouted to small_talk (F4); field-blind docstring |
| 13 | chat_d6d279fc | Corpus-bounds echo (F6) |
| 18 | chat_b4fc95b8 | Parse under-decomposition: no Analyze_Recommend goal for "similar to ISBN" |
| 25 | chat_a3899b74 | Corpus-bounds echo (F6); guides mapped "long/highly rated" reasonably |
| 26 | chat_09bbf318 | "Shorter than Dune" resolved from BookGuides absolutes, not Dune (pending-args gap) |
| 29 | chat_c5454969 | GitHub repo → out_of_scope though PROJECT_GITHUB_URL exists (field-blind docstring) |
| 33 | chat_897be0b6 | Excluded author also in positive `authors` (F1) |
| 36 | chat_4c630fce | Conditional recommend mislabeled Analyze_Compare → refused → half the ask silently dropped (F2) |
| 37 | chat_c8ad2cf6 | Accepted goal never covered by any task; zero trace (improvement #1) |
| 39 | chat_a2c66898 | Worst-case include/exclude contradiction — would return exactly the rejected genres (F1) |
| 41 | chat_aeaf42a3 | GOOD: unsupported Provide_Feedback goal refused with traceable reason |
| 42 | chat_2c204a27 | Excluded author echoed in positive `authors` (F1); otherwise excellent compound plan |
| 45 | chat_0cb2aa19 | Spurious recommend→project_info dependency (F7) |
| 49 | chat_6f4ce7be | Whole actionable message in small_talk + goal set; recommend goal lost (F4) |
| 50 | chat_5f30f32c | Feedback intent shoehorned into Retrieve_Developer_Info(bio) (F5); exclusion intent ("authors I've read") has no representable filter |

Everything not listed was clean or praiseworthy.

---

*Companion doc: `claude_improvements.md` — prioritized fixes and test plan.*
