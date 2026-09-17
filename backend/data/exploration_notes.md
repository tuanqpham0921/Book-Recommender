# Data Exploration Notes

## categories is high-cardinality free text
_2026-07-21 07:14_

480 distinct values across 5197 books; top value 'Fiction' covers 2111 of them. Not a clean facet to filter on as-is.

```sql
SELECT categories, count(*) FROM books GROUP BY categories ORDER BY 2 DESC
```

## categories is high-cardinality free text
_2026-07-21 10:28_

480 distinct values across 5197 books; top value 'Fiction' covers 2111 of them. Not a clean facet to filter on as-is.

```sql
SELECT categories, count(*) FROM books GROUP BY categories ORDER BY 2 DESC
```
