# backend/config

Configuration via pydantic-settings. Everything loads from **`config/.env`** (path
defined by `FilesLocationConstants.ENV_FILE` in `constants.py`).

## Usage

```python
from config import settings, FilesLocationConstants

settings.openai
settings.sqlalchemy
settings.app
```

`Settings` (`settings/main.py`) aggregates three sub-configs, each its own class and
file:

| Sub-config | File | Holds |
|---|---|---|
| `settings.app` | `settings/app.py` | App/environment settings |
| `settings.openai` | `settings/openai.py` | `OPENAI_API_KEY`, model options |
| `settings.sqlalchemy` | `settings/sqlalchemy.py` | `POSTGRES_*` connection settings |

## Adding or renaming an env var

Env var names are defined by the **field names/aliases in the sub-settings classes** —
change them there, not in `main.py`. To add a variable: add a field to the right
sub-settings class, then add the value to `config/.env`. Unknown keys in `.env` are
ignored (`extra="ignore"`).

## Constants

`constants.py` holds non-env constants: `FilesLocationConstants` (paths),
`AppConfig`, and domain constants. Prefer these over hard-coded paths/values.

Note: `.env` is gitignored — there is no Redis; the core variables are
`OPENAI_API_KEY` plus the `POSTGRES_*` set.
