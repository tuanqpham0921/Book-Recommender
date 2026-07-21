poetry run python /home/tuani/Book-Recommender/backend/evals/tools_catalog.py  
# Planner Tool Catalog

- generated: 2026-07-21 17:47:12 UTC
- commit: `3064dcb`
- tokenizer: `o200k_base` (via `--model gpt-4.1`)
- rates checked: 2026-07-21 (`config/pricing.py`)

Read from the live registry, not from a recorded run — this describes the code as it stands at the commit above.

## Summary

- **28 tools** registered
  - Analyze: 8
  - Other supported actions: 7
  - Retrieval: 13
- **5,721 tokens** in the rendered catalog block (5,694 in the tool descriptions themselves, the rest is tier headings and spacing)
- **27,386 tokens** if every tool's JSON schema were sent at once — but classification sends one per accepted goal, so a typical request pays a small fraction of this

## Cost per request

The catalog is prompt text on every request, used or not. It is byte-identical each time, so it is the most cache-friendly part of the prompt — expect the cached column in the steady state and the uncached one cold.

| call site | model | tokens | uncached | cached |
|---|---|---:|---:|---:|
| parse_intent._run_llm_args_parse (goal generation) | `gpt-4.1` | 5,721 | $0.011442 | $0.002861 |
| parse_intent.generate_user_response (user-facing reply) | `gpt-4.1-mini` | 5,721 | $0.002288 | $0.000572 |
| **per request** | | | **$0.013730** | **$0.003433** |

At 1,000 requests: $13.730400 uncached, $3.432600 cached — catalog text alone, before any user message, reasoning or output.

## Tools

`purpose` is the docstring's `Purpose:` line — the sentence that most decides whether the planner reaches for this tool. `catalog` = tokens this tool adds to every request. `schema` = tokens its JSON tool definition costs when classification selects it.

| node type | class | purpose | tier | catalog | share | schema | executor |
|---|---|---|---|---:|---:|---:|:---:|
| `Analyze_Recommend` | RecommendationStrategy | Suggest books that fit the user's ask — the analyze step for most recommendation queries. | Analyze | 350 | 6.1% | 1,297 | ✅ |
| `Retrieve_by_CoAuthors` | FindByCoAuthorsRetrieval | Retrieve books that two or more named authors wrote together — their collaborations. | Retrieval | 311 | 5.4% | 1,091 | ✅ |
| `Retrieve_by_Title` | FindByTitleRetrieval | Retrieve a single known book by its title from the database. | Retrieval | 307 | 5.4% | 1,111 | ✅ |
| `Retrieve_by_Author` | FindByAuthorRetrieval | Retrieve the books written by one named author — that author's bibliography. | Retrieval | 245 | 4.3% | 945 | ✅ |
| `Provide_Feedback` | FeedbackRequest | Record the user's feedback, opinion, bug report, or suggestion about this app itself. | Other supported actions | 239 | 4.2% | 944 | ✅ |
| `Retrieve_Project_Info` | ProjectInfoRequest | Retrieve information about the app, tech stack, architecture, or project metadata. | Retrieval | 229 | 4.0% | 956 | ✅ |
| `Retrieve_New_Releases` | NewReleasesRetrieval | Retrieve recently published books, optionally scoped by genre or other filters. | Retrieval | 225 | 3.9% | 1,736 | ❌ |
| `Analyze_Compare` | CompareStrategy | Contrast two or more named books — the analyze step when the user asks how titles differ or relate. | Analyze | 224 | 3.9% | 961 | ❌ |
| `Analyze_Summarize` | SummarizeStrategy | Summarize retrieved book(s) — plot, premise, or a focused angle. | Analyze | 209 | 3.7% | 961 | ❌ |
| `Analyze_Reading_Time` | ReadingTimeStrategy | Estimate how long retrieved book(s) will take to finish. | Analyze | 206 | 3.6% | 975 | ❌ |
| `Analyze_Reading_Plan` | ReadingPlanStrategy | Build a multi-book reading plan toward a stated goal or timeframe. | Analyze | 206 | 3.6% | 952 | ❌ |
| `Retrieve_Random` | RandomBookRetrieval | Retrieve a random pick from the catalog — a surprise with no taste signal. | Retrieval | 198 | 3.5% | 1,660 | ❌ |
| `Retrieve_Popular` | PopularBooksRetrieval | Retrieve widely read, highly rated books — what most people love. | Retrieval | 193 | 3.4% | 1,644 | ❌ |
| `Analyze_Reading_Level` | ReadingLevelStrategy | Assess age-appropriateness or difficulty of retrieved book(s). | Analyze | 192 | 3.4% | 897 | ❌ |
| `Analyze_Reading_Order` | ReadingOrderStrategy | Order a set of retrieved books into the sequence they should be read. | Analyze | 191 | 3.3% | 902 | ❌ |
| `Mark_Book_As_Read` | MarkBookAsReadAction | Record that the user finished a book, with an optional rating in the same breath. | Other supported actions | 189 | 3.3% | 859 | ❌ |
| `Retrieve_Series` | FindSeriesRetrieval | Retrieve every book belonging to a named series or saga. | Retrieval | 184 | 3.2% | 833 | ❌ |
| `Analyze_Themes` | ThemesStrategy | Extract the themes, motifs, or message of retrieved book(s). | Analyze | 182 | 3.2% | 869 | ❌ |
| `Rate_Book` | RateBookAction | Record the user's star rating for a book they already know. | Other supported actions | 179 | 3.1% | 822 | ❌ |
| `Retrieve_by_Genre` | FindByGenreRetrieval | Retrieve books belonging to a named genre or category from the database. | Retrieval | 176 | 3.1% | 784 | ✅ |
| `Retrieve_Author_Info` | AuthorInfoRetrieval | Retrieve facts about an author as a person — bio, style, background. | Retrieval | 173 | 3.0% | 827 | ❌ |
| `Retrieve_User_Info` | UserInfoRequest | Retrieve information about the current user from the database. | Retrieval | 168 | 2.9% | 822 | ✅ |
| `Retrieve_by_ISBN13` | FindByISBN13Retrieval | Retrieve a single book by its exact ISBN13 from the database. | Retrieval | 165 | 2.9% | 758 | ✅ |
| `Retrieve_Reading_Stats` | ReadingStatsRetrieval | Retrieve the user's reading statistics — counts, pages, genre breakdown. | Other supported actions | 164 | 2.9% | 806 | ❌ |
| `Retrieve_Reading_List` | ViewReadingListRetrieval | Show the user's reading list, optionally filtered by status. | Other supported actions | 155 | 2.7% | 753 | ❌ |
| `Retrieve_Developer_Info` | DeveloperInfoRequest | Retrieve information about the developer/maintainer of this app. | Retrieval | 154 | 2.7% | 784 | ✅ |
| `Save_To_Reading_List` | SaveToReadingListAction | Add named book(s) to the user's reading list. | Other supported actions | 144 | 2.5% | 723 | ❌ |
| `Remove_From_Reading_List` | RemoveFromReadingListAction | Remove named book(s) from the user's reading list. | Other supported actions | 136 | 2.4% | 714 | ❌ |

## Audit

- ⚠️ **No executor**: `Retrieve_Series`, `Retrieve_Author_Info`, `Retrieve_New_Releases`, `Retrieve_Popular`, `Retrieve_Random`, `Analyze_Compare`, `Analyze_Summarize`, `Analyze_Themes`, `Analyze_Reading_Order`, `Analyze_Reading_Level`, `Analyze_Reading_Time`, `Analyze_Reading_Plan`, `Save_To_Reading_List`, `Retrieve_Reading_List`, `Remove_From_Reading_List`, `Mark_Book_As_Read`, `Rate_Book`, `Retrieve_Reading_Stats`. The planner can plan these, but `TaskRunnerWorkflow` has nothing to run — they cost catalog tokens on every request and fail if selected.

