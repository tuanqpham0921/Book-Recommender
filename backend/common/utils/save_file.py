import json
import logging
from pathlib import Path


from config import FilesLocationConstants
from common.utils.format import remove_json_empty_values, to_serializable

logger = logging.getLogger(__name__)

def save_file(
    data,
    file_name: str = "log",
    path: Path | str = FilesLocationConstants.EXPORT_DIR,
    remove_empty_values: bool = True,
):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)

    jsonable = to_serializable(data)
    if remove_empty_values:
        jsonable = remove_json_empty_values(jsonable)

    json_str = json.dumps(jsonable, indent=2, default=str)

    file_name = file_name.rstrip(".json")
    filepath = path / f"{file_name}.json"
    with open(filepath, "w") as f:
        f.write(json_str)
    
    if logger:
        logger.info(f"📋 log written to {filepath}")
    else:
        print(f"📋 log written to {filepath}")