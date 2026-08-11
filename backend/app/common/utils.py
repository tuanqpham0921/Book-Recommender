from typing import Iterable
from collections import Counter

def count_values(values: Iterable[str | None]) -> dict[str, int]:
    """`{value: how many books had it}`, commonest first.

    Blanks are dropped rather than counted as a group: "3 books with no genre"
    is a fact about the catalog, not about the recommendation, and both
    readers of these summaries (the run log and the response generator) would
    be misled by it.
    """
    return dict(Counter(value for value in values if value).most_common())