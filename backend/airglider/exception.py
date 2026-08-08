class StepFailure(RuntimeError):
    """Control-flow only: raised by run_async_step to abort a workflow's
    remaining steps after a step failed. The failing step's own envelope
    already records the details (including runtime_error if it crashed), so
    __call__ logs a single summary line and does not stamp runtime_error."""