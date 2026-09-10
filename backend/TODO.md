# TODO (scratchpad)

Durable planning lives in [/docs](../docs/README.md) — roadmap, backlog, eval strategy,
and design decisions. This file is only for in-flight scribbles that die within a
session; anything worth keeping graduates into a `docs/` file.

## Migration log

**2026-07-17** — V1 scoping → `docs/design/node-taxonomy-v1.md` + `docs/roadmap.md`;
code-review/security findings, test gaps, workflow-framework notes → `docs/backlog.md`;
golden-test/suite notes → `docs/eval-strategy.md`.

**2026-08-19** — "make the node args parse choose the tool → `ok=False` message back to
the planner", the `num_books == 0` propagation bug, and "add more nodes before over
debugging" → `docs/design/node-refusal-v1.md` (+ two backlog bullets under "Node contracts
& refusal").

**2026-09-07 (a)** — the sink-vs-slice sketch ("if a node failed then you have to go and
find it") → `docs/design/execution-pipeline-v1.md`, under the second generation-node
attempt. Answered by the failure artifacts: a failed goal leaves a `FailedGoalOutput` and
the runner composes the reason naming the upstream cause, so the generation node is handed
the failure instead of having to go looking for it.

**2026-09-07 (b) — full sweep against the code.** ~700 lines went out. Where they went:

| What it was | Where it is now |
|---|---|
| Retries design; `@task` idempotency question | `docs/backlog.md` → Workflow framework, items 6–7 |
| HITL scope limits; the intersect/CTE pause point; "you can't go back" | `docs/design/human-in-the-loop.md` → "Status update — 2026-09-07" |
| Nested routing inside the recommend node vs. a flat planner (~90 lines) | `docs/design/planner-shape.md` → open experiment 4 |
| Duplicate goals; domain pre-filtering as a catalog shrink | `docs/design/planner-shape.md` → open experiment 3 |
| "Can't answer what isn't a column" (main characters, plot) | `docs/design/node-taxonomy-v1.md` → V1 conversation contract |
| Two kinds of compare; the winner-as-filter insight; edge pruning | `docs/design/node-taxonomy-v1.md` → Future considerations |
| SQLAlchemy pooled-connection GC warning (was a raw log paste) | `docs/backlog.md` → Reliability |
| Rate-limit capacity arithmetic (15 requests/plan, 500 RPM) | `docs/backlog.md` → Reliability |
| `confidence` 0.0; analyze→analyze prompt examples; first-person reasoning | `docs/backlog.md` → Planner quality |
| Compact tracer; `add_details(log=True)`; finish the Responses API migration | `docs/backlog.md` → Tracing, clients & tooling |
| Batching several counts into one round trip | `docs/backlog.md` → Performance |
| "Why?" button; nodes calling the planner; bounded multi-turn loop; narration field; pre-made plans; unified artifact renderer | `docs/backlog.md` → Ideas pool |
| Session factories on stores; per-node parsing; bounds-after-search; the 0.7 floor; generation as a sink | `docs/backlog.md` → Settled (all decided the other way) |

Also restored: **`docs/design/human-in-the-loop.md`**, which five docs link to and which
was lost in the `5df0d80` revert.

Deleted as already built — the code is the record: the architecture "Guidelines" block and
the re-architecture plan (that *is* the current architecture), `OperationResult.input`,
`parse_intent`'s removal, the genre node (now `Retrieve_by_Lexical_Traits`), the
collect/filter node (now `Combine_Intersect`), SSE section events (`task.start`/`task.end`),
tasks returning typed outputs, the `Analyze_Recommend` → `Analyze_Similar_Books` rename, the
`published after 2015` docstring gap, and the generation-node deliberation.

Two items were already tracked and were **not** duplicated: the "Brave New World" title
match is `docs/backlog.md` → Planner quality ("`Retrieve_by_Title` should prefer exact
matches"), and retry/backoff is the same decision as the rate-limit item under Reliability.

Historical cleanup logs live in git history (`git log -p -- backend/TODO.md`).

---

## In flight

- **What the generation node feeds its writer.** `write_recommendations/render.py` currently
  sends full book entries — title, author, year, rating, 400-char blurb, up to 12k chars.
  The alternative is the old `analyze_recommend` shape: counts and ranges only (authors,
  shelves, page span), with the books reaching the user as cards and never reaching the LLM.
  Recoverable at `git show 8b03c8e^:backend/app/domains/books/analyze_recommend/generate_response.py`
  and its `prompts/response_prompt.txt`. The tradeoff is per-book "why this fits" (needs
  blurbs) against a reply that cannot invent a plot (needs their absence). Undecided.

* format the task runner result better
    * should contain books for small input (find by titles and such)
    * maybe the operation result is the output
      * just have the steps summary
    * make sure that the books data only have useful fields
      * so no thumbnail, isbn and such

* format the results better
  * task runner should not be responsible for reasons
  * it should not modify or anything
  * it should only store and receive results
  * which is how you can have the business logic into the generation node.

* up to here the goal is
  * having some structure data that can be saved into db
  * with source id or task id
  * this will be the source of truth for generation and continuation (for later)
    * whatever this contain, the system can answer

* make sure this work first
  * so you can mock tasks "output"
  * so you can eval test the generation response

* then I think the idea is have this
  * do a pre-parse in the generation workflow into

class section:
  title or query to answer
  sources = list[task ids] <- will be send at the end

then you have list[sections]
format it into 1 generation node

assistant_msg = [
<section 1>
  * query or title
  * generate the answer
  * book cards
</section1>

<section 2>
  same thing
</section>
]

so it's similar to the dynamic generation
but instead of pre_assigning
you can post assign it
since some might fail or not

so the section will choose from the work output
into smaller sections

* maybe forget about streaming for now
