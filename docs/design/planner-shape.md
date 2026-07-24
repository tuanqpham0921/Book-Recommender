# Planner shape: capability nodes vs. entity + intent (decision record)

**Date:** 2026-07-24 · **Status:** accepted for V1 — revisit as a V2 cost optimization

Graduated from `backend/TODO.md` (the "book entity" experiment notes, 2026-07-21/24).
The node set this decision produces is recorded in
[node-taxonomy-v1.md](node-taxonomy-v1.md); the phases that build on it are in
[../roadmap.md](../roadmap.md).

## The question

The planner's first stage has to turn a sentence into something structured. Two shapes
were on the table, and the repo has now tried both:

- **Capability nodes (current).** One request schema per thing the system can do —
  `Retrieve_by_Title`, `Retrieve_by_Author`, `Retrieve_by_Genre`, `Analyze_Recommend`, …
  The LLM picks a node type and fills that node's small argument set.
- **Entity + intent.** One generic `BookEntity` extraction (title, authors, genre, page
  range, year, rating …) plus a separate intent identifier (compare / recommend /
  look up), linked afterwards.

## Evidence for the entity shape

Real, and the reason it kept coming back:

- Noticeably faster, and it works acceptably on a **smaller model** — less decision-making
  asked of the LLM per call.
- Fewer tokens: one database request schema instead of N node docstrings in the catalog.
- Multiple identifiers could be extracted **concurrently**.

## Why V1 keeps capability nodes anyway

1. **The catalog is the capability contract.** Because each node is a separate registered
   schema, the tool catalog literally states what the system can and cannot do. There is
   no `published_year` node, so nothing offers to filter on publication year. With one
   big entity, every field is implicitly on offer, and removing a capability means editing
   a system prompt and re-running a whole-entity eval instead of deleting a registry line.
2. **One big field is hard to constrain case by case.** "Get books with 100–200 pages,
   fiction" has no author in it, but a wide entity schema invites the model to fill
   `authors` anyway. Preventing that means prompt examples per field — book-specific
   wording back in a prompt that [roadmap Phase 2](../roadmap.md) deliberately made
   generic.
3. **The entity still has to be linked, and linking is the expensive part.** The whole
   entity blob would have to be passed into a linker/intent step. That is worse for prompt
   caching (the blob varies every request, unlike the byte-identical catalog) and it
   re-introduces the second call the entity shape was supposed to save.
4. **The analyze nodes are already intents.** Going entity-first would still require an
   intent identifier plus a linkage step — `compare_books(entity[book1, book2])` is the
   same graph the current planner already produces. The rewrite would arrive back at the
   present design, one abstraction later.
5. **Adding a field is cheap and local.** New capability → new schema + registry line +
   eval cases (`backend/app/domains/README.md`). The system prompt stays generic, which is
   the property that makes this planner reusable outside the book domain.

**Accepted tradeoff:** V1 pays more tokens and one extra LLM call for determinism, a
generic prompt, and a catalog that cannot over-promise. Cost reduction is a V2 project,
and the entity shape is the leading candidate there — possibly as a *split* entity
(retrieval-task goals + intent goals, then link), which is close to what exists now.

**Supporting measurement:** verbose docstrings are worth their tokens; shipping each
node's full pydantic model instead would cost roughly **1k more tokens per node**. Run
`make tools-catalog` to see the current per-tool cost and the per-request catalog price,
cached and uncached.

## Open experiments (not decided)

### 1. System goals as the dependency linker

Today: `parse_intent` produces goals, `strategy_classification` fills arguments *and*
resolves `depends_on`. The experiment is to have the goal stage emit dependencies too
(`goal_1`, `goal_2` …), validated against `NodeTypeEnum`, and measure completion cost.

- **For:** goals and tasks are already 1-1, so if goals carry the dependencies, every
  argument parser could run **independently and in parallel**. The dependency field is
  cheap — it is just goal ids, not prose. The goal `description` already doubles as a
  rewrite of the user's query for the parser, which is useful on its own.
- **Against:** the goal stage becomes the planner *and* the source of truth. If even a
  frontier model misclassifies often, there is no second opinion; keeping the parser and
  linkage separate leaves room for best-effort injection, and the parser doubles as a
  mistake catcher. Completion cost may rise, and it may need reasoning fields or better
  query normalization to hold quality.
- **Related:** `depends_on` may be droppable from the parser entirely, since each goal
  already carries exactly one `node_type`.
- **Retrieval intent:** retrieval nodes may want a `purpose` field (for reference, for
  verification, for information). Worked example — *"Did Jane Austen write Dune?"* becomes
  `Retrieve_by_Title` with the goal *"Find Dune by Jane Austen to verify authorship"*;
  the intent is currently only implied by the goal description.

### 2. Vector embeddings for routing and retrieval

`book_store.search_by_embedding` already exists. Unmeasured questions:

- Single-word embeddings for **genre** and **author names** — how closely related do near
  misses actually score?
- Embedding a composed record ("title, page count, description …") and querying it
  semantically — would *"find books with 100 pages"* be caught by similarity alone, or
  does it need the structured filter path?

### 3. Planner semantics still unanswered

- Should the model be allowed to **infer contradictory constraints**, or must it refuse?
  (Adversarial suite territory — the clarification node in
  [roadmap Phase 1](../roadmap.md) is the mechanism either way.)
- Do system goals need explicit **numbering**, or is multi-step ordering enough?
- Should small talk and gibberish be filtered **before** the goal stage rather than
  becoming goals? (See [backlog.md](../backlog.md).)
- Was the planner's edge-linking separation optimized away too early? Recorded here so
  the question survives; the answer likely comes from executor work, not more planner
  tinkering.

## Standing note

From the owner's 2026-07-24 entry, and the reason this record exists: *"I think I can
tinker with the planner and system goals forever. It works well enough for now. I need to
get the executors in, because then I know what they need first and I can go back to the
planner."* The 2026-07-24 eval baseline (157/164, see [../eval-strategy.md](../eval-strategy.md))
is the evidence that the planner is good enough to build on — every remaining red traces
to the one node that was never built, not to routing quality.
