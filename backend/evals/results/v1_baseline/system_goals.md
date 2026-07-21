# Eval suite system-goals report

- generated: 2026-07-21 16:05:47 UTC
- commit: `e687f98`
- suites: query_suite, query_suite_adversarial, query_suite_extended, query_suite_stress

**Overall:** 3/8 matched (5 mismatched, 0 without expectations, 8 cases total)

### `query_suite`

| case | difficulty | query | result | missing | extra | run ok | chat_id |
|---|---|---|---|---|---|---|---|
| 1 | easy | What is the book Dune? | ✅ match | — | — | ✅ | `chat_f365efca` |
| 2 | easy | Find the book with ISBN 9780385333481. | ✅ match | — | — | ✅ | `chat_75b30817` |

**query_suite:** 2/2 matched (0 mismatched, 0 without expectations, 2 cases total)

### `query_suite_adversarial`

| case | difficulty | query | result | missing | extra | run ok | chat_id |
|---|---|---|---|---|---|---|---|
| 301 | medium | Find books with more than -50 pages and fewer than -10 pages… | ❌ mismatch | Retrieve_by_Traits | — | ✅ | `chat_1519d64d` |
| 302 | medium | Find books published in the year 300 BC. | ❌ mismatch | Retrieve_by_Traits | — | ✅ | `chat_cbdc6a87` |

**query_suite_adversarial:** 0/2 matched (2 mismatched, 0 without expectations, 2 cases total)

### `query_suite_extended`

| case | difficulty | query | result | missing | extra | run ok | chat_id |
|---|---|---|---|---|---|---|---|
| 101 | easy | What other books did Agatha Christie write? | ✅ match | — | — | ✅ | `chat_993bc918` |
| 102 | easy | Show me all the books in the Mistborn series. | ❌ mismatch | Retrieve_Series | Retrieve_by_Author | ✅ | `chat_20dbe87e` |

**query_suite_extended:** 1/2 matched (1 mismatched, 0 without expectations, 2 cases total)

### `query_suite_stress`

| case | difficulty | query | result | missing | extra | run ok | chat_id |
|---|---|---|---|---|---|---|---|
| 401 | hard | Find all of these books: Dune, Foundation, Neuromancer, 1984… | ❌ mismatch | — | Retrieve_by_Title, Retrieve_by_Title, Retrieve_by_Title, Retrieve_by_Title, Retrieve_by_Title, Retrieve_by_Title, Retrieve_by_Title, Retrieve_by_Title, Retrieve_by_Title | ✅ | `chat_2bbbf779` |
| 402 | hard | Recommend me a mystery book, recommend a sci-fi book, recomm… | ❌ mismatch | Analyze_Recommend | — | ❌ | `chat_9cc28651` |

**query_suite_stress:** 0/2 matched (2 mismatched, 0 without expectations, 2 cases total)

