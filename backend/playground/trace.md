Orchestrator_record
    * TriageWorkflow
        * load_cached_parse_output -> return TriageOutput
        * planner = PlanJaneExecutor
            * parse_result = llm_args_parse (form filling)
            * process_parse_result()
            * return PlanJaneOutput
        * return TriageOutput(planner)

    * TaskRunnerWorkflow
        * order
        * process unreachable
        * result = {}
        for layer in loop:
            for goal in layer:
                * prep = prepare
                    * get spec
                    * get executor
                    * narrow(ctx)
                    * build the input
                        * add to detail
                * if prep is None: 
                    * add to fail continue
                * run the task
                    * send sse_start start
                    * run step_result
                * if failed:
                    * add to failed_task, continue
                * store and continue
                