poetry run python /home/tuani/Book-Recommender/backend/evals/tools_catalog.py  
# Planner Tool Catalog

- generated: 2026-07-21 17:35:05 UTC
- commit: `9e129ca`
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

`catalog` = tokens this tool adds to every request. `schema` = tokens its JSON tool definition costs when classification selects it.

| node type | class | tier | catalog | share | schema | executor |
|---|---|---|---:|---:|---:|:---:|
| `Analyze_Recommend` | RecommendationStrategy | Analyze | 350 | 13.5% | 1,297 | ✅ |
| `Retrieve_by_CoAuthors` | FindByCoAuthorsRetrieval | Retrieval | 311 | 12.0% | 1,091 | ✅ |
| `Retrieve_by_Title` | FindByTitleRetrieval | Retrieval | 307 | 11.8% | 1,111 | ✅ |
| `Retrieve_by_Author` | FindByAuthorRetrieval | Retrieval | 245 | 9.4% | 945 | ✅ |
| `Provide_Feedback` | FeedbackRequest | Other supported actions | 239 | 9.2% | 944 | ✅ |
| `Retrieve_Project_Info` | ProjectInfoRequest | Retrieval | 229 | 8.8% | 956 | ✅ |
| `Analyze_Compare` | CompareStrategy | Analyze | 224 | 8.6% | 961 | ❌ |
| `Retrieve_by_Genre` | FindByGenreRetrieval | Retrieval | 176 | 6.8% | 784 | ✅ |
| `Retrieve_User_Info` | UserInfoRequest | Retrieval | 168 | 6.5% | 822 | ✅ |
| `Retrieve_by_ISBN13` | FindByISBN13Retrieval | Retrieval | 165 | 6.4% | 758 | ✅ |
| `Retrieve_Developer_Info` | DeveloperInfoRequest | Retrieval | 154 | 5.9% | 784 | ✅ |

## Audit

- ⚠️ **No executor**: `Analyze_Compare`. The planner can plan these, but `TaskRunnerWorkflow` has nothing to run — they cost catalog tokens on every request and fail if selected.

