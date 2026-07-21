# Eval suite cost report

- generated: 2026-07-21 16:05:47 UTC
- commit: `e687f98`
- suites: query_suite, query_suite_adversarial, query_suite_extended, query_suite_stress

### Overall

| cases | ok | failed | runtime errors | total tokens | avg tokens | cached tokens | cache hit | total cost | avg cost | avg duration |
|---|---|---|---|---|---|---|---|---|---|---|
| 8 | 7 | 1 | 0 | 55053 | 6882 | 18816 | 37.7% | $0.0064 | $0.000795 | 8.74s |

> ⚠️ **Costs below are understated.** No rate for `gpt-4.1` when these runs were recorded, so their tokens are counted but their spend is not. Add them to `config/pricing.py` — re-running this report will not backfill it, since `cost_usd` is frozen at record time.

### Spend by model

| model | tokens | prompt | cached | completion | cache hit |
|---|---|---|---|---|---|
| `gpt-4.1` | 29,324 | 28,418 | 15,872 | 906 | 55.9% |
| `gpt-5-nano` | 13,189 | 9,063 | 0 | 4,126 | 0.0% |
| `gpt-4.1-mini` | 12,540 | 12,437 | 2,944 | 103 | 23.7% |

### `query_suite`

| cases | ok | failed | runtime errors | total tokens | avg tokens | cached tokens | cache hit | total cost | avg cost | avg duration |
|---|---|---|---|---|---|---|---|---|---|---|
| 2 | 2 | 0 | 0 | 13763 | 6882 | 3968 | 30.9% | $0.0010 | $0.000498 | 7.64s |

| case | difficulty | query | ok | error | duration | tokens | cached | cost | chat_id | session |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | easy | What is the book Dune? | ✅ | — | 8.5s | 6880 | 0 | $0.000475 | `chat_f365efca` | `test_96e38f63` |
| | | _Single FindByTitle. Simplest possible book lookup — one node, exact title, no am…_ | | | | | | | | |
| 2 | easy | Find the book with ISBN 9780385333481. | ✅ | — | 6.8s | 6883 | 3968 | $0.000520 | `chat_75b30817` | `test_96e38f63` |
| | | _Single FindByISBN13. Most precise retrieval — ISBN is unambiguous, zero inferenc…_ | | | | | | | | |

### `query_suite_adversarial`

| cases | ok | failed | runtime errors | total tokens | avg tokens | cached tokens | cache hit | total cost | avg cost | avg duration |
|---|---|---|---|---|---|---|---|---|---|---|
| 2 | 2 | 0 | 0 | 16774 | 8387 | 6912 | 41.8% | $0.0026 | $0.001303 | 5.27s |

| case | difficulty | query | ok | error | duration | tokens | cached | cost | chat_id | session |
|---|---|---|---|---|---|---|---|---|---|---|
| 301 | medium | Find books with more than -50 pages and fewer than -10 pages. | ✅ | — | 5.7s | 8399 | 0 | $0.001744 | `chat_1519d64d` | `test_9a10c280` |
| | | _BooksFilter.min_pages/max_pages have no ge/le constraints (db/schema/filter_sche…_ | | | | | | | | |
| 302 | medium | Find books published in the year 300 BC. | ✅ | — | 4.8s | 8375 | 6912 | $0.000862 | `chat_cbdc6a87` | `test_9a10c280` |
| | | _min_year/max_year are plain Optional[int] with no bound tied to BookConstraints …_ | | | | | | | | |

### `query_suite_extended`

| cases | ok | failed | runtime errors | total tokens | avg tokens | cached tokens | cache hit | total cost | avg cost | avg duration |
|---|---|---|---|---|---|---|---|---|---|---|
| 2 | 2 | 0 | 0 | 14210 | 7105 | 7936 | 61.6% | $0.0011 | $0.000573 | 8.72s |

| case | difficulty | query | ok | error | duration | tokens | cached | cost | chat_id | session |
|---|---|---|---|---|---|---|---|---|---|---|
| 101 | easy | What other books did Agatha Christie write? | ✅ | — | 7.8s | 6873 | 3968 | $0.000494 | `chat_993bc918` | `test_48a85814` |
| | | _Single FindByAuthor. Author is the subject — must not route to Retrieve_by_Title…_ | | | | | | | | |
| 102 | easy | Show me all the books in the Mistborn series. | ✅ | — | 9.7s | 7337 | 3968 | $0.000652 | `chat_20dbe87e` | `test_48a85814` |
| | | _Single FindSeries. Series referenced as a whole — not a title lookup._ | | | | | | | | |

### `query_suite_stress`

| cases | ok | failed | runtime errors | total tokens | avg tokens | cached tokens | cache hit | total cost | avg cost | avg duration |
|---|---|---|---|---|---|---|---|---|---|---|
| 2 | 1 | 1 | 0 | 10306 | 5153 | 0 | 0.0% | $0.0016 | $0.000807 | 13.33s |

| case | difficulty | query | ok | error | duration | tokens | cached | cost | chat_id | session |
|---|---|---|---|---|---|---|---|---|---|---|
| 401 | hard | Find all of these books: Dune, Foundation, Neuromancer, 1984, Brave New World, F… | ✅ | — | 25.1s | 9589 | 0 | $0.001318 | `chat_2bbbf779` | `test_204e5037` |
| | | _Twenty single-title lookups in one message — well past MAX_SYSTEM_GOALS=10 and M…_ | | | | | | | | |
| 402 | hard | Recommend me a mystery book, recommend a sci-fi book, recommend a romance, recom… | ❌ | — | 1.5s | 717 | 0 | $0.000296 | `chat_9cc28651` | `test_204e5037` |
| | | _Thirteen goals spanning every current node type (Analyze_Recommend, Retrieve_by_…_ | | | | | | | | |

