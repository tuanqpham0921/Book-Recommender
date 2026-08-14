class StepFailure(RuntimeError):
    """Control-flow only: raised by `OperationResult.unwrap` (and by
    `Workflow.run_async_step`) to abort the caller after a step it needed
    failed.

    The failing step's own envelope already holds the details, including the
    `runtime_error` of whatever actually crashed, so `record_span` reports this
    as a stop — stamped like any other failure, but logged as one warning line
    naming the step, with no traceback. See span.py.
    """