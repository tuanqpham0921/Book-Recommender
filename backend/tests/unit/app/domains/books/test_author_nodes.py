"""Contract tests for the author retrieval split (2026-07-21).

`Retrieve_by_Author` used to carry `authors: list[str]` meaning "one combined
bibliography", which could only ever express an OR — so "what did X and Y write
together" was unreachable. It is now one author per node, with
`Retrieve_by_CoAuthors` owning the AND. These tests pin the two field
constraints that keep those apart; the docstrings that teach the planner LLM
which is which are covered generically by test_registry.py.

See docs/design/node-taxonomy-v1.md ("Author split").
"""

import pytest
from pydantic import ValidationError

from app.domains.books.node_types import BookNodeTypeEnum
from app.domains.books.schemas import (
    FindByAuthorRetrieval,
    FindByCoAuthorsRetrieval,
)
from app.registry import EXECUTORS_CLS_MAPPING, NODE_TYPE_TO_CLS

# the DomainRequest fields every node carries, so each test only states the
# author fields it actually cares about
BASE = {
    "id": "task_1",
    "description": "d",
    "reasoning": "r",
    "confidence": 0.9,
    "target_goal": ["goal_1"],
}


class TestFindByAuthorRetrieval:
    def test_takes_exactly_one_author(self):
        task = FindByAuthorRetrieval(**BASE, author="Ursula K. Le Guin")

        assert task.author == "Ursula K. Le Guin"
        assert task.node_type == BookNodeTypeEnum.FIND_AUTHOR

    def test_a_list_of_authors_is_rejected(self):
        # the whole point of the split: several authors' separate
        # bibliographies is several nodes, not one node with a list
        with pytest.raises(ValidationError):
            FindByAuthorRetrieval(**BASE, author=["Jane Austen", "Paulo Coelho"])


class TestFindByCoAuthorsRetrieval:
    def test_takes_two_or_more_authors(self):
        task = FindByCoAuthorsRetrieval(
            **BASE, authors=["Brian Herbert", "Kevin J. Anderson"]
        )

        assert task.authors == ["Brian Herbert", "Kevin J. Anderson"]
        assert task.node_type == BookNodeTypeEnum.FIND_COAUTHORS

    @pytest.mark.parametrize("authors", [[], ["Solo Author"]])
    def test_fewer_than_two_authors_is_rejected(self, authors):
        # a single author has nobody to have collaborated with — that query
        # belongs to Retrieve_by_Author, so the schema refuses to accept it
        # here rather than silently degrading into a bibliography lookup
        with pytest.raises(ValidationError):
            FindByCoAuthorsRetrieval(**BASE, authors=authors)


class TestRegistration:
    def test_both_nodes_are_registered_and_distinct(self):
        assert NODE_TYPE_TO_CLS["Retrieve_by_Author"] is FindByAuthorRetrieval
        assert NODE_TYPE_TO_CLS["Retrieve_by_CoAuthors"] is FindByCoAuthorsRetrieval

    def test_both_nodes_have_an_executor(self):
        # a registered node with no executor is planned then fails at run time
        assert FindByAuthorRetrieval in EXECUTORS_CLS_MAPPING
        assert FindByCoAuthorsRetrieval in EXECUTORS_CLS_MAPPING
