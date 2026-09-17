poetry run python /home/tuani/Book-Recommender/backend/evals/tools_catalog.py  
# Planner Tool Catalog

- generated: 2026-07-21 17:47:55 UTC
- commit: `3064dcb`
- tokenizer: `o200k_base` (via `--model gpt-4.1`)
- rates checked: 2026-07-21 (`config/pricing.py`)

Read from the live registry, not from a recorded run — this describes the code as it stands at the commit above.

## Summary

- **11 tools** registered
  - Analyze: 2
  - Other supported actions: 1
  - Retrieval: 8
- **2,595 tokens** in the rendered catalog block (2,568 in the tool descriptions themselves, the rest is tier headings and spacing)
- **10,453 tokens** if every tool's JSON schema were sent at once — but classification sends one per accepted goal, so a typical request pays a small fraction of this

## Cost per request

The catalog is prompt text on every request, used or not. It is byte-identical each time, so it is the most cache-friendly part of the prompt — expect the cached column in the steady state and the uncached one cold.

| call site | model | tokens | uncached | cached |
|---|---|---:|---:|---:|
| parse_intent._run_llm_args_parse (goal generation) | `gpt-4.1` | 2,595 | $0.005190 | $0.001298 |
| parse_intent.generate_user_response (user-facing reply) | `gpt-4.1-mini` | 2,595 | $0.001038 | $0.000260 |
| **per request** | | | **$0.006228** | **$0.001557** |

At 1,000 requests: $6.228000 uncached, $1.557000 cached — catalog text alone, before any user message, reasoning or output.

## Tools

`purpose` is the docstring's `Purpose:` line — the sentence that most decides whether the planner reaches for this tool. `catalog` = tokens this tool adds to every request. `schema` = tokens its JSON tool definition costs when classification selects it.

| node type | class | purpose | tier | catalog | share | schema | executor |
|---|---|---|---|---:|---:|---:|:---:|
| `Analyze_Recommend` | RecommendationStrategy | Suggest books that fit the user's ask — the analyze step for most recommendation queries. | Analyze | 350 | 13.5% | 1,297 | ✅ |
| `Retrieve_by_CoAuthors` | FindByCoAuthorsRetrieval | Retrieve books that two or more named authors wrote together — their collaborations. | Retrieval | 311 | 12.0% | 1,091 | ✅ |
| `Retrieve_by_Title` | FindByTitleRetrieval | Retrieve a single known book by its title from the database. | Retrieval | 307 | 11.8% | 1,111 | ✅ |
| `Retrieve_by_Author` | FindByAuthorRetrieval | Retrieve the books written by one named author — that author's bibliography. | Retrieval | 245 | 9.4% | 945 | ✅ |
| `Provide_Feedback` | FeedbackRequest | Record the user's feedback, opinion, bug report, or suggestion about this app itself. | Other supported actions | 239 | 9.2% | 944 | ✅ |
| `Retrieve_Project_Info` | ProjectInfoRequest | Retrieve information about the app, tech stack, architecture, or project metadata. | Retrieval | 229 | 8.8% | 956 | ✅ |
| `Analyze_Compare` | CompareStrategy | Contrast two or more named books — the analyze step when the user asks how titles differ or relate. | Analyze | 224 | 8.6% | 961 | ❌ |
| `Retrieve_by_Genre` | FindByGenreRetrieval | Retrieve books belonging to a named genre or category from the database. | Retrieval | 176 | 6.8% | 784 | ✅ |
| `Retrieve_User_Info` | UserInfoRequest | Retrieve information about the current user from the database. | Retrieval | 168 | 6.5% | 822 | ✅ |
| `Retrieve_by_ISBN13` | FindByISBN13Retrieval | Retrieve a single book by its exact ISBN13 from the database. | Retrieval | 165 | 6.4% | 758 | ✅ |
| `Retrieve_Developer_Info` | DeveloperInfoRequest | Retrieve information about the developer/maintainer of this app. | Retrieval | 154 | 5.9% | 784 | ✅ |

## Audit

- ⚠️ **No executor**: `Analyze_Compare`. The planner can plan these, but `TaskRunnerWorkflow` has nothing to run — they cost catalog tokens on every request and fail if selected.

