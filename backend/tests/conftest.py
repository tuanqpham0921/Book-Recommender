import pandas as pd
import pytest

collect_ignore = ["unit/db/ingestion/test_ingestion_utils.py"]


@pytest.fixture
def sample_books() -> pd.DataFrame:
    from config import FilesLocationConstants
    return pd.read_csv(FilesLocationConstants.DATA_DIR / "test_books.csv")
