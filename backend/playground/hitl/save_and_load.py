# NOTE: try to save the orchestration record
# and load it back in exactly

# current implmentation is difficult
# and need to have reload back or set the workflow again

# some ideas might be passing in the old task runner
# and artifacts and generate new plans
# using the old plans and artifacts as prefix
# tho that is a re-plan hitl rather than a button confirmation thing

record = None
try:
    from airglider import OperationResult
    from common.utils import load_json, save_file, print_json
    save_file(record, "og_record")
    
    print("heree")
    r_json = load_json('og_record', path='logs')
    print_json(r_json)
    print("-------------------------")
    r = OperationResult.model_validate(r_json)
    print(r.name, r.ok, r.token_usage.total, len(r.flatten()), 'spans')
    save_file(r, 'remade_record')
    
    print(record == r)
    
except Exception as e:
    print(e)