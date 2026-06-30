"""Tests for config/settings/"""
import pytest

from config.settings import AppSettings, OpenAISettings, Settings, SQLAlchemySettings


def make_sqlalchemy(**overrides) -> SQLAlchemySettings:
    defaults = dict(
        HOST="localhost",
        PORT=5432,
        DB="mydb",
        USER="alice",
        PASSWORD="secret",
        MIN_CONNECTIONS=2,
        MAX_CONNECTIONS=10,
    )
    return SQLAlchemySettings.model_construct(**{**defaults, **overrides})


class TestSQLAlchemySettingsUrl:
    def test_tcp_url_format(self):
        s = make_sqlalchemy(HOST="localhost", PORT=5432, DB="mydb", USER="alice", PASSWORD="secret")
        assert s.sqlalchemy_url == "postgresql+asyncpg://alice:secret@localhost:5432/mydb"

    def test_cloudsql_url_format(self):
        s = make_sqlalchemy(HOST="/cloudsql/project:region:instance", DB="mydb", USER="alice", PASSWORD="secret")
        assert s.sqlalchemy_url == "postgresql+asyncpg://alice:secret@/mydb?host=/cloudsql/project:region:instance"

    def test_tcp_when_host_does_not_start_with_cloudsql(self):
        s = make_sqlalchemy(HOST="10.0.0.1", PORT=5432)
        assert "10.0.0.1:5432" in s.sqlalchemy_url

    def test_cloudsql_when_host_starts_with_cloudsql_prefix(self):
        s = make_sqlalchemy(HOST="/cloudsql/anything")
        assert "?host=/cloudsql/anything" in s.sqlalchemy_url
        assert "@/" in s.sqlalchemy_url  # no host:port in the URL authority

    def test_url_contains_asyncpg_driver(self):
        assert make_sqlalchemy().sqlalchemy_url.startswith("postgresql+asyncpg://")

    def test_url_embeds_credentials(self):
        s = make_sqlalchemy(USER="bob", PASSWORD="hunter2")
        assert "bob:hunter2@" in s.sqlalchemy_url

    def test_url_contains_database_name(self):
        s = make_sqlalchemy(DB="books")
        assert "books" in s.sqlalchemy_url


class TestOpenAISettings:
    def test_fields_stored_correctly(self):
        s = OpenAISettings.model_construct(
            API_KEY="sk-test",
            BASE_MODEL="gpt-4o",
            TOKENIZER_ENCODING="cl100k_base",
            EMBEDDING_MODEL="text-embedding-3-small",
            EMBEDDING_DIMENSIONS=1536,
            MAX_CONCURRENCY=5,
        )
        assert s.API_KEY == "sk-test"
        assert s.BASE_MODEL == "gpt-4o"
        assert s.EMBEDDING_DIMENSIONS == 1536
        assert s.MAX_CONCURRENCY == 5


class TestAppSettings:
    def test_fields_stored_correctly(self):
        s = AppSettings.model_construct(
            NAME="book-recommender",
            ENVIRONMENT="test",
            ALLOW_ORIGINS="http://localhost:3000",
        )
        assert s.NAME == "book-recommender"
        assert s.ENVIRONMENT == "test"
        assert s.ALLOW_ORIGINS == "http://localhost:3000"


class TestSettings:
    def test_has_all_sub_settings(self):
        s = Settings.model_construct(
            sqlalchemy=make_sqlalchemy(),
            openai=OpenAISettings.model_construct(
                API_KEY="sk-test",
                BASE_MODEL="gpt-4o",
                TOKENIZER_ENCODING="cl100k_base",
                EMBEDDING_MODEL="text-embedding-3-small",
                EMBEDDING_DIMENSIONS=1536,
                MAX_CONCURRENCY=5,
            ),
            app=AppSettings.model_construct(
                NAME="book-rec",
                ENVIRONMENT="test",
                ALLOW_ORIGINS="*",
            ),
        )
        assert isinstance(s.sqlalchemy, SQLAlchemySettings)
        assert isinstance(s.openai, OpenAISettings)
        assert isinstance(s.app, AppSettings)
