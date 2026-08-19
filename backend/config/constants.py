from pathlib import Path
""" Centralized constants for the application.
Makefile and docker compose will need to update (manually) if these are changed.
"""

PROJECT_ROOT = Path(__file__).resolve().parent.parent

class AppConfig:
    """System-level constants."""
    SESSION_PREFIX   = "session"
    DATABASE_TIMEOUT = 10.0  # SQLAlchemy engine init / connectivity
    OPENAI_TIMEOUT   = 10.0
    DEFAULT_TIMEOUT  = 10.0


class OpenAIConstants:
    MAX_TOKENS = 100_000

class FilesLocationConstants:
    """Repository paths resolved from the backend package root."""

    PROJECT_ROOT = PROJECT_ROOT
    DATA_DIR = PROJECT_ROOT / "data"
    # CSV_FILE = "books.csv"
    CSV_FILE = "test_books.csv"
    
    ENV_FILE = PROJECT_ROOT / "config" / ".env"
    
    EXAMPLE_PROMPT_DIR = DATA_DIR / "prompt_example"
    PROMPTS_DIR = PROJECT_ROOT / "app"
    EXPORT_DIR = PROJECT_ROOT / "logs"
    PAYLOAD_DIR = EXPORT_DIR / "payloads"
    
    BACKUP_DIR = DATA_DIR / "backup"
    SCHEMA_DIR = PROJECT_ROOT / "db" / "schema"
    SCHEMA_EXTENSIONS_FILE = SCHEMA_DIR / "00_extensions.sql"
    SCHEMA_TABLES_FILE = SCHEMA_DIR / "01_tables.sql"
    SCHEMA_INDEXES_FILE = SCHEMA_DIR / "02_indexes.sql"
    
    LOG_DIR = PROJECT_ROOT / "logs"

class BookConstraints:
    """Domain constraints for book data."""
    MIN_PAGE_COUNT = 4
    MAX_PAGE_COUNT = 3342
    
    MIN_RATING = 0.0
    MAX_RATING = 5.0
    
    MIN_PUBLISHED_YEAR = 1876
    MAX_PUBLISHED_YEAR = 2019

    # How close a book has to sit to the embedded description to count as a
    # candidate at all, as cosine similarity. Without a floor the vector search
    # returns its top N however far away they are — the whole table ordered,
    # truncated — so an ask with no near match comes back full of strangers.
    # Deliberately permissive: enforced now (see `embedding_search_stmt`), and
    # `similarity_score` is recorded on every recommended book in `chat_runs`,
    # so tune this off the real distribution rather than off a guess.
    MIN_SIMILARITY = 0.35

    MIN_LIMIT = 1
    MAX_LIMIT = 5
    default_limit = 3

    def __str__(self):
        """Return string representation of all constraints."""
        result = "BookConstraints:\n"
        
        # Get all class attributes that are constants (uppercase or constraint names)
        constraints = {
            name: value for name, value in self.__class__.__dict__.items()
            if not name.startswith('_') and not callable(value)
        }
        
        for attr_name, attr_value in constraints.items():
            result += f"  {attr_name} = {attr_value}\n"

        return result