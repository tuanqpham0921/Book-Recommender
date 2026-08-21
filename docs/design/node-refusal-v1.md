# When a node can't do the work: refusal and empty results (design record)

**Date:** 2026-08-19 · **Status:** **Proposed, deliberately deferred.** Nothing here is
built. One half of the second problem was partly addressed on 2026-08-18 (noted below);
the rest is parked until the node set is fuller. Graduated from `backend/TODO.md`.

Two bugs found while running the three-node end-to-end path on
`refactor_minimal_end_to_end_v1`. They look unrelated — one is a planner routing problem,
one is a count of zero — but they share a root: **a node that was handed work it cannot
do has no way to say so.** Its only vocabulary is `ok=True` (which claims it did the job)
or a raise (which claims the code broke). The honest third answer — "I ran fine, and this
was the wrong node for this" — does not exist yet.

## Where the node set stands today

Three nodes are registered (`app/domains/books/guide.py`): `Retrieve_by_Title`,
`Filter_Retrieval`, `Analyze_Recommend`. The other eight in the V1 taxonomy are parked —
the code is importable, the SPEC is not in the guide, so the planner never sees them
([node-taxonomy-v1.md](node-taxonomy-v1.md)). Run `make tools-catalog` for what is
actually live rather than trusting this paragraph.

**That is 3 of 11, and the missing 8 include every node that answers a thematic ask.**
`Retrieve_by_Genre` is parked. `Retrieve_Random` — promoted specifically to serve the bare
"recommend me a book" with no anchor — is parked. So a request that names no title has no
legal plan at all.

> **Amended 2026-08-21 — the menu gap is mostly closed.** Six nodes are registered now:
> `Retrieve_by_Title`, `Retrieve_by_Author`, **`Retrieve_by_Category`**,
> `Retrieve_by_Numeric_Traits`, `Filter_Retrieval`, `Analyze_Recommend`.
> `Retrieve_by_Category` is what the paragraph above calls `Retrieve_by_Genre`, built wider
> and renamed ([node-taxonomy-v1.md](node-taxonomy-v1.md)), and it answers thematic asks
> directly — "give me a book about war" now has a legal plan. `Retrieve_Random` is still
> parked, so the bare "recommend me a book" with no anchor at all still does not.
>
> **This makes the doc's own trigger live** (see "What would say it's time" below): the
> catalog is no longer the obvious explanation for a mis-route, so mis-routing observed
> from here is evidence about routing quality rather than about a gap in the menu. The
> second problem — a node with no way to say "I ran fine, and this was the wrong node" —
> is untouched and still the reason this record exists.

## Symptom: "give me a book about war"

The planner sometimes emits `Retrieve_by_Title` → `Analyze_Recommend` for it. The title
node then parses `title="war"` (`FindByTitleArgs.title` is a required `str`, and the parse
is forced — see below), counts the books with "war" in the title, and hands that query on
as if it were an anchor.

**This is out of capability right now, not a node-level bug.** The planner is doing what
the catalog told it to: `RecommendationStrategy`'s docstring says *"needs a supporting
retrieval step, so a retrieval is still required even for purely thematic requests with no
named book"* — and with `Retrieve_by_Genre` and `Retrieve_Random` parked at the time, the only
supporting retrieval on the menu is the title node. Given the catalog it was shown, the
plan is the best available one; it is the catalog that is wrong.

There is precedent for reading it that way. The 2026-07-17 eval review recorded the same
class of finding — expected `Analyze_Recommend`, got `Retrieve_by_Traits` — and concluded
*"the planner isn't wrong so much as the schemas are … prompt tuning alone would have
plateaued here"* ([eval-strategy.md](../eval-strategy.md)). The fix there was structural,
and it is structural here too.

## Problem 1 — the args parser cannot decline

### What happens now

`OpenAIParserRequest.to_payload` (`clients/openai_requests.py`) pins `tool_choice` to the
single tool model:

```python
payload["tool_choice"] = {"type": "function", "function": {"name": ...}}
```

The parse is therefore **mandatory**. The model cannot answer "this ask has no title in
it"; it must produce a `FindByTitleArgs`, so it produces `title="war"`. Downstream, that
is indistinguishable from a real title search. The node finalizes `ok=True` — correctly,
by its own claim, which is "args parsed and query built".

### Proposed

Let the parser **choose** the tool instead of being forced into it. When it declines, its
text response *is* the refusal — "wrong usage, this node needs book titles or artifacts" —
and the node finalizes **`ok=False` with no runtime error**, carrying that message so the
planner can be handed it and reply with a clear out-of-capability answer instead of a
title search for "war".

### What this changes that is already written down

`backend/app/domains/README.md` (executor rule 2) currently says: *"Raise when the node
cannot proceed; **never hand-set `ok=False` and return**."* This proposal introduces
exactly the state that rule forbids, so adopting it means amending that rule rather than
quietly breaking it.

The reason to amend it is the wart the same README already names: a business dead-end that
raises and a genuine crash both land in `runtime_error`, so the record cannot tell "could
not proceed" from "the code broke" (see also the review-page item in
[backlog.md](../backlog.md), and `StepFailure`'s interim treatment). A mis-routed goal is a
*third* thing — the node worked perfectly and the plan was wrong — and it is the one the
planner can actually act on. Raising is the worst of the three ways to report it.

### Touch points when this is built

| | |
|---|---|
| `clients/openai_requests.py` | `tool_choice` pinned in `OpenAIParserRequest.to_payload`; needs to become optional per request |
| `app/domains/base_workflow.py` | `run_llm_tool_calls` raises `ValueError("LLM response contained no tool calls")` — that path becomes the refusal, not an error |
| each slice's `finalize_result` | today `ok` is computed off `self.result.args is not None`; a declined parse leaves `args` None, which already reads as not-ok — the missing half is the *message* |
| `app/orchestration/task_runner.py` | a not-ok node is appended to `failed_task` and dropped from `results`; a refusal needs to survive as something the reply can quote |

Open, not decided: whether the refusal text rides on a new output field or on `details`;
and whether the planner is re-invoked in the same turn (there is no re-plan loop today —
the turn is single-pass).

## Problem 2 — `num_books == 0` is `ok=True`, which is right for the producer and wrong for the consumer

### The current contract

`BookRetrievalOutput`'s docstring: *"`num_books == 0` is a real answer: nothing matched,
not a failure."* And executor rule 2: *"An empty result is not a failure to claim … For an
analyze node that owns the turn's reply, the claim therefore ends at answered:
`Analyze_Recommend` writes 'nothing that short sits near those books' and finalizes ok,
because raising would surface as the generic failure message and tell the user nothing
about what was too tight."*

That reasoning holds and should stay. It exists so the eventual generation step gets an
answer to write from rather than a stack trace.

### Where it breaks

It breaks one step later, in a node that consumes artifacts. A 0-count retrieval hands
downstream a perfectly valid `ok=True` output whose query reaches no rows. Composed into
`Analyze_Recommend`'s anchor, that is an OR branch that costs a scan and contributes
nothing — while making the anchor *look* populated.

**Partly addressed 2026-08-18.** `ParsedDependents.from_anchors`
(`app/domains/books/analyze_recommend/dependents.py`) now sorts a 0-count anchor into a
separate `empty` pile instead of pooling its query, and the executor raises when every
anchor is empty. That is option 2b below, plus a raise. It is also the raise-shaped
version of Problem 1 — if refusal existed, that raise would be an `ok=False` refusal
instead.

### The options

1. **Answer in the producing node.** The node that counted zero writes the user-facing
   line itself, and nothing downstream has to interpret an empty artifact.
2. **Don't pass it on.** Either the task runner withholds 0-count outputs from dependents,
   or each consumer's dependency-parsing drops them (**done** for the recommend node).
3. **Skip the consumer.** When *every* dependency of a node is empty, skip the node rather
   than running it against nothing.

They are not exclusive, and 1 and 3 pull against each other. The NOTE already sitting in
`TaskRunnerWorkflow._dependency_outputs` states the cost: if every node answers for
itself, the user reads *"I found no books"* in one section and *"because there were no
books, I can't continue"* in the next. **One generation node at the end is the shape that
resolves this**, and it does not exist yet
([execution-pipeline-v1.md](execution-pipeline-v1.md) — "Nothing turns executor output
into prose. The final assistant message has no owner.").

So option 1 is cheap now and gets deleted when generation lands; option 3 is the one that
survives it.

## Why this is deferred

- **More nodes sharpen boundaries.** The eval evidence is that routing quality is a
  function of how well the catalog covers the ask, not of prompt polish. With 3 of 11
  nodes live, "give me a book about war" has no correct plan to find — tuning refusal
  against that catalog is tuning against a distribution that will not exist in a month.
- **Triage and plan caching cut the same errors upstream**, before a node ever sees a
  mis-routed goal.
- **Evals plus unit/integration tests find these more cheaply than debugging by hand.**
  Both bugs here were found by running the pipeline and reading traces; the second one had
  no test coverage at all until the `ParsedDependents` suite was written on 2026-08-18.
- **The V1.1 conversation seams are involved.** A refusal that travels back to the planner
  is a re-plan loop, which is the same machinery as clarification — better designed once,
  with that, than bolted on now.

## What would say it's time

- ~~`Retrieve_by_Genre` and `Retrieve_Random` are registered~~ — **half met 2026-08-21.**
  `Retrieve_by_Category` (the wider node that replaced the genre sketch) is registered, so
  "give me a book about war" has a legal plan. If it still mis-routes, that is real routing
  quality rather than a gap in the menu. `Retrieve_Random` is still parked, so the bare
  anchorless "recommend me a book" remains a menu gap rather than evidence.
- `make suite-goals` shows mis-routing that is not explained by a parked node.
- A generation node exists, so option 3 above has somewhere to put its explanation.
