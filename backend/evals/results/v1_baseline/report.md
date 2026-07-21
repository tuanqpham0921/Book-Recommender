# Eval suite cost report

- generated: 2026-07-21 16:27:41 UTC
- commit: `28f6ef1`
- suites: query_suite

### Overall

| cases | ok | failed | runtime errors | total tokens | avg tokens | cached tokens | cache hit | total cost | avg cost | avg duration |
|---|---|---|---|---|---|---|---|---|---|---|
| 3 | 3 | 0 | 0 | 21712 | 7237 | 9472 | 47.9% | $0.0162 | $0.005409 | 8.69s |

### Spend by model

| model | tokens | prompt | cached | completion | cache hit |
|---|---|---|---|---|---|
| `gpt-4.1` | 12,412 | 12,139 | 7,936 | 273 | 65.4% |
| `gpt-5-nano` | 7,364 | 5,711 | 1,536 | 1,653 | 26.9% |
| `gpt-4.1-mini` | 1,936 | 1,921 | 0 | 15 | 0.0% |

### `query_suite`

| cases | ok | failed | runtime errors | total tokens | avg tokens | cached tokens | cache hit | total cost | avg cost | avg duration |
|---|---|---|---|---|---|---|---|---|---|---|
| 3 | 3 | 0 | 0 | 21712 | 7237 | 9472 | 47.9% | $0.0162 | $0.005409 | 8.69s |

| case | difficulty | query | ok | error | duration | tokens | cached | cost | chat_id | session |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | easy | What is the book Dune? | ✅ | — | 5.6s | 6926 | 5504 | $0.003151 | `chat_964fe5a8` | `test_998a97ed` |
| | | _Single FindByTitle. Simplest possible book lookup — one node, exact title, no am…_ | | | | | | | | |
| 2 | easy | Find the book with ISBN 9780385333481. | ✅ | — | 8.9s | 6943 | 0 | $0.009317 | `chat_6367cd32` | `test_998a97ed` |
| | | _Single FindByISBN13. Most precise retrieval — ISBN is unambiguous, zero inferenc…_ | | | | | | | | |
| 3 | easy | Recommend me a mystery book. | ✅ | — | 11.5s | 7843 | 3968 | $0.003760 | `chat_52edec72` | `test_998a97ed` |
| | | _Single Recommend with semantic input only. One genre keyword, no reference book,…_ | | | | | | | | |

