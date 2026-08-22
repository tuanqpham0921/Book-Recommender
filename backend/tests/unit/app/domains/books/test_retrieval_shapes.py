"""Which half of the retrieval split each registered node produces.

`BookAnchorOutput` and `BookCandidateOutput` add no fields, so there is nothing
to test *on* them — the type is the payload, and what these assert is that
`build_input` selects on it. The point of the split is that a node depending on
anchors cannot be handed a subject search: the refusal happens at dispatch,
naming the field, instead of inside the node after two round trips.

The parenting assertions are the ones that fail loudly if a slice is reparented
by accident, since nothing else in the app reads these classes yet — both
consumers (`Filter_Retrieval`, `Analyze_Recommend`) are parked.
"""

import pytest
from pydantic import Field, ValidationError

from app.domains.books.external import (
    BookAnchorOutput,
    BookCandidateOutput,
    BookRetrievalOutput,
)
from app.domains.books.find_by_author.external import FindByAuthorOutput
from app.domains.books.find_by_category.external import FindByCategoryOutput
from app.domains.books.find_by_numeric_traits.external import (
    FindByNumericTraitsOutput,
)
from app.domains.books.find_by_title.external import FindByTitleOutput
from app.domains.node_input import NodeInput, build_input

CANDIDATE_OUTPUTS = (
    FindByAuthorOutput,
    FindByCategoryOutput,
    FindByNumericTraitsOutput,
)


class _NeedsAnAnchor(NodeInput):
    """What the similarity search will declare: anchors, and no fallback."""

    anchors: list[BookAnchorOutput] = Field(..., min_length=1)


class _TakesEither(NodeInput):
    """What a node narrowing either kind declares."""

    upstream: list[BookAnchorOutput | BookCandidateOutput] = []


class TestWhichHalfEachNodeProduces:
    def test_title_is_an_anchor(self):
        assert issubclass(FindByTitleOutput, BookAnchorOutput)

    @pytest.mark.parametrize("output_cls", CANDIDATE_OUTPUTS)
    def test_the_described_searches_are_candidates(self, output_cls):
        assert issubclass(output_cls, BookCandidateOutput)

    @pytest.mark.parametrize(
        "output_cls", (FindByTitleOutput, *CANDIDATE_OUTPUTS)
    )
    def test_both_halves_are_still_retrieval_outputs(self, output_cls):
        """`ParsedDependents.from_anchors` and `filter_books.anchor_queries`
        both gate on the base, and neither slice was touched by the split."""
        assert issubclass(output_cls, BookRetrievalOutput)

    def test_the_base_is_still_concrete(self):
        """It is what a node declares when it takes either, and what a combine
        node whose shape depends on its inputs can subclass. Making it abstract
        would force that choice at class-definition time."""
        assert BookRetrievalOutput(num_books=3).num_books == 3


class TestAnchorSelection:
    def test_a_candidate_is_not_collected_as_an_anchor(self):
        anchor = FindByTitleOutput(num_books=1)
        built = build_input(
            _NeedsAnAnchor,
            "recommend books like Dune",
            {"1": anchor, "2": FindByCategoryOutput(num_books=358)},
        )
        assert built.anchors == [anchor]

    def test_only_candidates_upstream_is_refused_by_name(self):
        """The whole point: 358 mysteries cannot anchor a similarity search, and
        the plan is refused at dispatch naming `anchors` — which `_prepare`
        turns into one skipped goal — rather than inside the node."""
        with pytest.raises(ValidationError) as excinfo:
            build_input(
                _NeedsAnAnchor,
                "recommend me a cozy mystery",
                {"1": FindByCategoryOutput(num_books=358)},
            )

        assert [err["loc"] for err in excinfo.value.errors()] == [("anchors",)]


class TestTakingEither:
    def test_a_union_field_collects_both_halves(self):
        anchor = FindByTitleOutput(num_books=1)
        candidate = FindByNumericTraitsOutput(num_books=2190)
        built = build_input(
            _TakesEither, "q", {"1": anchor, "2": candidate}
        )
        assert built.upstream == [anchor, candidate]
