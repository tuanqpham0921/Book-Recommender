"""`OperationResult.input` — what a workflow was called with, on its envelope.

Two rules carry the weight here:

1. **Keyed by parameter name**, so `f(x)` and `f(arg=x)` record identically —
   an index-keyed record would store the same call two ways.
2. **A value that can summarize itself does.** A node's input carries the
   output of the node before it, and that output's own envelope already holds
   every field of it. Dumping it again would store the same payload once per
   dependent, growing the trace with the square of a plan's depth.

The recording must also never take down the run it describes, which is the
last class below.
"""

import asyncio

import pytest
from pydantic import BaseModel

from airglider import OperationResult, Workflow, current_parent, task


class _Payload(BaseModel):
    """Stands in for an upstream node output: big, and already recorded in
    full on its own envelope."""

    rows: list[str] = []

    def to_summary(self) -> dict:
        return {"num_rows": len(self.rows)}


class _Input(BaseModel):
    query: str = ""
    anchors: list[_Payload] = []


class _Recorded(Workflow):
    async def run(self, node_input, extra=None):
        self.record.ok = True


class _Exploding(Workflow):
    async def run(self, node_input):
        raise RuntimeError("boom")


class TestParameterNames:
    async def test_a_positional_argument_is_keyed_by_its_name(self):
        wf = _Recorded()
        await wf(_Input(query="find dune"))

        assert wf.record.input == {"node_input": {"query": "find dune", "anchors": []}}

    async def test_keyword_and_positional_record_identically(self):
        positional, keyword = _Recorded(), _Recorded()
        await positional(_Input(query="q"))
        await keyword(node_input=_Input(query="q"))

        assert positional.record.input == keyword.record.input

    async def test_an_argument_the_caller_omitted_is_absent(self):
        """No `apply_defaults()`: the record says what was passed, so a call
        with one argument does not read as a wall of defaults."""
        wf = _Recorded()
        await wf(_Input())

        assert wf.record.input is not None
        assert "extra" not in wf.record.input

    async def test_no_arguments_records_none_rather_than_an_empty_dict(self):
        class _NoArgs(Workflow):
            async def run(self):
                self.record.ok = True

        wf = _NoArgs()
        await wf()

        assert wf.record.input is None


class TestSummarizing:
    async def test_a_payload_that_can_summarize_itself_does(self):
        """The anchor's rows live on the upstream node's envelope; this one
        records that there were three of them."""
        anchor = _Payload(rows=["a", "b", "c"])
        wf = _Recorded()
        await wf(_Input(query="q", anchors=[anchor]))

        assert wf.record.input is not None
        assert wf.record.input["node_input"]["anchors"] == [{"num_rows": 3}]

    async def test_a_value_without_a_summary_is_recorded_whole(self):
        """The small, unique parts of a call — the query text, parsed args —
        are exactly what the record is for."""
        wf = _Recorded()
        await wf(_Input(query="books like dune"))

        assert wf.record.input is not None
        assert wf.record.input["node_input"]["query"] == "books like dune"


class TestFailurePaths:
    async def test_a_crashing_workflow_still_records_its_input(self):
        """The call that crashed is the one worth knowing the arguments of —
        which is why the stamp happens before run(), not after."""
        wf = _Exploding()
        await wf(_Input(query="q"))

        assert wf.record.runtime_error is not None
        assert wf.record.input == {"node_input": {"query": "q", "anchors": []}}

    async def test_a_cancelled_workflow_still_records_its_input(self):
        class _Cancelling(Workflow):
            async def run(self, node_input):
                raise asyncio.CancelledError

        wf = _Cancelling()
        with pytest.raises(asyncio.CancelledError):
            await wf(_Input(query="q"))

        assert wf.record.input == {"node_input": {"query": "q", "anchors": []}}

    async def test_a_broken_summary_does_not_take_down_the_run(self):
        """`to_summary` is app code this library does not control. A missing
        `input` is a worse trade than a failed turn."""

        class _BadSummary(BaseModel):
            def to_summary(self):
                raise ValueError("summary exploded")

        wf = _Recorded()
        await wf(_BadSummary())

        assert wf.record.ok
        assert wf.record.input is None

    async def test_arguments_that_do_not_fit_the_signature_record_nothing(self):
        """Binding must not pre-empt the call's own, much better error."""
        wf = _Recorded()
        await wf(wrong_name="x")

        assert wf.record.input is None
        assert wf.record.runtime_error is not None
        assert isinstance(wf.record.runtime_error.type, str)


class TestSerializability:
    async def test_the_record_survives_a_json_round_trip(self):
        """`input` lands in the chat_runs JSONB column with the rest of the
        tree, so anything left in it has to be encodable."""
        wf = _Recorded()
        await wf(_Input(query="q", anchors=[_Payload(rows=["a"])]))

        reloaded = OperationResult.model_validate_json(
            wf.record.model_dump_json()
        )
        assert reloaded.input == wf.record.input

    async def test_a_live_handle_is_reduced_to_its_type_name(self):
        """Arguments are not payloads a caller chose to record — they are
        whatever the function takes, and a DB session or client reaching the
        envelope would break the JSONB insert far from where it came from."""

        class _Session:
            pass

        @task(log_info=False)
        async def _uses_a_session(session):
            return "done"

        result = await _uses_a_session(_Session())

        assert result.input == {"session": "<_Session>"}
        # the whole point: the envelope still encodes
        assert "_Session" in result.model_dump_json()


class TestTaskDecorator:
    async def test_a_task_records_its_arguments(self):
        @task(log_info=False)
        async def _add(left, right):
            return left + right

        result = await _add(2, right=3)

        assert result.input == {"left": 2, "right": 3}

    async def test_a_method_does_not_record_its_receiver(self):
        """`self` is args[0] for a decorated method — recording the whole
        client is noise, and for a non-serializable one, a hazard."""

        class _Client:
            @task(log_info=False)
            async def fetch(self, key):
                return key

        result = await _Client().fetch("k")

        assert result.input == {"key": "k"}

    async def test_a_crashing_task_records_what_it_was_called_with(self):
        """This envelope carries no output, so the arguments are the only
        description of the failure beyond the traceback."""

        @task(log_info=False)
        async def _explodes(key):
            raise ValueError("boom")

        result = await _explodes("k")

        assert not result.ok
        assert result.input == {"key": "k"}

    async def test_a_body_may_overwrite_its_own_recorded_input(self):
        """A task that resolved something more meaningful than its raw
        arguments writes over them on the envelope it is already running in."""

        @task(log_info=False)
        async def _custom(key):
            parent = current_parent()
            assert parent is not None
            parent.input = {"resolved": "something better"}
            return None

        result = await _custom("k")

        assert result.input == {"resolved": "something better"}

    async def test_a_rejected_envelope_still_records_the_arguments(self):
        # the input is stamped before the call, so it survives every failure
        # path — including the body returning an envelope
        @task(log_info=False)
        async def _custom(key):
            return OperationResult(ok=True)

        result = await _custom("k")

        assert result.ok is False
        assert result.runtime_error is not None
        assert result.runtime_error.type == "TypeError"
        assert result.input == {"key": "k"}
