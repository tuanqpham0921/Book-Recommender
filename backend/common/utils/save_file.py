import json
import logging
from dataclasses import asdict, is_dataclass
from pathlib import Path

from config import FilesLocationConstants

logger = logging.getLogger(__name__)


def save_file(
    data,
    file_name: str = "log",
    path: Path | str = FilesLocationConstants.EXPORT_DIR,
):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)

    if is_dataclass(data):
        data = asdict(data)

    json_str = json.dumps(data, indent=2, default=str)
    filepath = path / f"{file_name}.json"
    with open(filepath, "w") as f:
        f.write(json_str)

    if logger:
        logger.info(f"📋 log written to {filepath}")
    else:
        print(f"📋 log written to {filepath}")
