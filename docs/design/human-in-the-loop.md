# Human-in-the-loop: pause, persist, resume (design record)

**Date:** 2026-07-24 · **Status:** proposed — pause point not chosen, nothing implemented

Graduated from `backend/TODO.md` (2026-07-24). The owner's assessment, recorded because it
drives the roadmap: **this is the highest-ROI feature left**, and it is also the one most
likely to force architecture changes — which is exactly why the pause point is chosen on
paper first.

## What HITL means here

Interrupt a run mid-flight, show the user what the system is about to do, and continue
from that point after they answer — rather than running to completion and apologizing.

Mechanically it needs four pieces that do not exist yet:

1. **A pause event** streamed to the frontend (SSE), with the question and the choices.
2. **Trace persistence** — the run's state saved at the pause, not just logged.
3. **A resume endpoint** — new API surface; today the whole surface is
   `POST /session/{id}/message` and the review/feedback routes.
4. **Rehydration** — load the saved trace back into live workflow objects and keep going
   with the user's answer injected.

Piece 4 is where the difficulty is, and it is the reason for the blockers section below.

## Candidate pause points

### A. After the planner — "here's the plan, continue?"

**Easiest and most testable.** The plan already streams to the frontend as a Mermaid
diagram, so the UI half is nearly free, and the state to persist is exactly one
`StrategyClassificationOutput`.

Complication: it has to be designed against `TaskRunnerWorkflow`, which is meant to run
tasks concurrently (`for task in tasks: … run step`). A confirm gate that sits *before*
the runner starts avoids that entirely; a gate *inside* the loop does not.

### B. At the system-goal stage — "this will be expensive, continue?"

Mock the goal stage into returning a large number of goals, then warn about token spend
before any of them run. Attractive because the same pattern then generalizes down to task
executors: any step that can estimate its own cost can gate on it.

### C. After retrieval counts — "4,000 horror books, narrow it down?"

The most *useful* to a real user, and it falls straight out of the
[execution pipeline](execution-pipeline-v1.md) shape where retrieval returns counts rather
than rows. It cannot be built before executors are real — mock executors would have to
fake a count large enough to trigger it, which tests the plumbing but not the feature.

## Known blockers (verified 2026-07-24)

**1. The strategy output cannot be round-tripped for most node types.**
`StrategyClassificationOutput.accepted/buffer/refused` are typed
`list[AnyStrategyRequest]`, a discriminated union with **10 members**, while the live
registry has **28 registered node types**. Constructing the model from saved JSON — the
exact operation resume performs — raises `ValidationError` for `Analyze_Compare` and all
17 extension node types. It does not fail today only because the workflow appends to the
list in place (pydantic does not validate `list.append`), and serialization survives via
duck-typing with a `PydanticSerializationUnexpectedValue` warning. Resume turns a latent
mismatch into a hard failure. Tracked in [../backlog.md](../backlog.md); fixing it is
cheap and can be done independently, well before any HITL work starts.

**2. Child-workflow progress is lost on interrupt.** Steps are appended only *after* a
child finishes (`run_async_step` → await → `add_steps`), so an interrupted run has no
record of partial child progress. Better checkpointing needs incremental `add_steps` and
a rethink of result append/overwrite semantics — item 4 of the Workflow-framework list in
[../backlog.md](../backlog.md). A pause point that sits *between* workflows (A or B)
dodges this; one that sits inside a running task does not.

**3. `Workflow` keeps state in private attributes.** Backlog item 3 — state needs to live
in the output (possibly `create` instead of `parse`) before a workflow can be
reconstructed from a saved trace at all.

**4. There is no server-side stop.** `stopChatStream` exists client-side with no backend
endpoint (roadmap deferred list). Pause/resume and stop want the same plumbing.

## Guardrail: nothing stays alive waiting

Carried over from the owner's 2026-07-17 conversation-readiness notes, and recorded here
because HITL is the first feature that can violate it. The intended pause semantics are
**zero-resource**:

> The turn **ends normally**. The next user message resumes the work by reading the saved
> `chat_runs` trace. No workflow, task, or connection stays alive holding state while the
> system waits for a human.

This is what keeps V1.1's conversation work additive rather than a re-architecture. A
"pause" implemented as a suspended coroutine, a held SSE connection, or an in-memory
session registry would satisfy the demo and break the design. Concretely, a pause must:

- finalize and persist the run like any completed turn (`assistant_message` + the planner
  JSONB trace both stay — do not trim persistence to save space);
- carry enough state in that trace to reconstruct the plan without the original process;
- treat the user's answer as an ordinary next message that happens to resume something.

Related tripwires worth re-checking whenever this area is touched: the clarification node
must not become a special-cased dead end, `parse_intent.py`'s prompt assembly should not
collapse into a single opaque string, and `Orchestrator` finalize must keep recording on
every path.

## Status update — 2026-09-07 (graduated from `backend/TODO.md`)

**This file was lost in the `5df0d80` revert and restored 2026-09-07.** Five docs link to
it (README, roadmap ×2, backlog, execution-pipeline ×2); the content below 2026-07-24 is
as it was written then, with these corrections.

**Blocker 1 is fixed.** `Registry.request_union()` builds the union from the registered
specs on demand, so it cannot drift from the registry any more (backlog, Correctness —
resolved 2026-08-10). The prerequisite named under "Recommendation" is done.

**Pause point C is now buildable, and it is what the counts-first pipeline was for.**
Retrieval nodes count and hand on a `DeferredBookQuery` without fetching rows, and
`Combine_Intersect` composes those queries into one CTE — so *"4,000 horror books, narrow
it down?"* is a number the system already has at every step, for free, before anything is
materialized. The owner's note, from the commit that added the intersect:

> at each step I can do a CTE to ensure that there are books (candidates) — if none or too
> many then I can ask the user … with this split I can do things like "my database has 500
> sci-fi, I have also 10 books by Jane Austen".

The same counts already stream as `ui_loading` lines ("checking how many books have 200
pages or more"), so the UI half is nearly free the way pause point A's diagram was.

**An empty intersect needs no question, which is the useful asymmetry.** If a *component*
retrieval is large the user might want to narrow it; if the **intersection** is empty, the
answer is already known — no book matches all the criteria — and there is nothing to relax
that would change it. Same for an exclusion set ("books I haven't read"): empty means they
have read everything matching, which is an answer, not a prompt. So a gate belongs where a
count is *large*, not where it is zero.

### The open problem: a gate mid-DAG cannot go back

```
filter1 ─┐
         ├─→ intersect
filter2 ─┘
```

Pausing at the intersect lets the user constrain or relax **that** step, but the two
upstream retrievals have already run and their arguments are fixed. Re-opening one means
re-planning a subgraph, which is the "cut-off re-plan (remove this node) or complete
re-plan" the owner already flagged as out of scope. Two candidate answers, neither chosen:

- **Gate only at the end** — one pause before the terminal node, where every count is
  known and the whole plan is still re-runnable as a unit. Simplest, and it matches
  pause point A's "nothing mid-flight" property.
- **Stop rather than ask** — when an upstream branch comes back empty, end the turn with
  the reason instead of gating. This is close to what the failure artifacts already do:
  the generation node is handed a `FailedGoalOutput` and tells the user what came back
  empty, without a round trip.

### Scope limits carried over

- **HITL is for choosing among options the system generated, not for free text.** A user
  given a text box will type *"actually compare them instead"*, which is a re-plan, not a
  resume. Deterministic choices only — narrow / relax / proceed / stop.
- **It is human-in-the-loop without a loop.** There is no iteration primitive; a pause is
  one turn ending and the next turn resuming from the saved trace (see the guardrail
  above).
- **At retrieval, a pause is a *hint*, not a gate.** Where a fuzzy title match is
  uncertain, the useful question is a confirmation ("did you mean this one?"), and a
  declined match means dropping those books from the next step — not blocking the plan.
  The natural gate is still an analyze node, where an over-broad set costs real embedding
  work.

## Recommendation

Build **A** first — a confirm gate placed *before* `TaskRunnerWorkflow` starts, so no
concurrency or checkpoint semantics are touched. It proves the whole loop end to end
(event → persist → endpoint → rehydrate → continue) against the single simplest piece of
state in the system, and it makes B and C incremental instead of foundational.

Prerequisite either way: fix blocker 1. It is a small change to a union, and it is the
difference between "resume works" and "resume works except for 18 node types".

## Related

- [execution-pipeline-v1.md](execution-pipeline-v1.md) — where pause point C comes from.
- [node-taxonomy-v1.md](node-taxonomy-v1.md) — "HITL re-rank" was already noted there as a
  natural fit for the recommendation node; that is a *later* application of this
  machinery, not the first cut.
- [../roadmap.md](../roadmap.md) — deferred list already carries "Checkpoint/resume +
  incremental step recording" and "Server-side stop".
