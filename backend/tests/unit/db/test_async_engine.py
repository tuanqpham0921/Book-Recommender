"""Tests for db/async_engine.py"""

from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from config.settings import SQLAlchemySettings
from db.async_engine import (
    check_connection,
    close_async_engine,
    get_async_engine,
    get_session_factory,
)


def make_settings(**overrides) -> SQLAlchemySettings:
    defaults = dict(
        HOST="localhost",
        PORT=5432,
        DB="testdb",
        USER="user",
        PASSWORD="pass",
        MIN_CONNECTIONS=2,
        MAX_CONNECTIONS=10,
    )
    return SQLAlchemySettings.model_construct(**{**defaults, **overrides})


def make_session_factory(scalar_value=1):
    """Build a mock async session factory that returns `scalar_value` from SELECT 1."""
    mock_result = MagicMock()
    mock_result.scalar.return_value = scalar_value

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_factory


class TestGetAsyncEngine:
    def test_returns_async_engine(self):
        with patch("db.async_engine.create_async_engine") as mock_create:
            mock_create.return_value = MagicMock(spec=AsyncEngine)
            engine = get_async_engine(make_settings())
        assert engine is mock_create.return_value

    def test_passes_sqlalchemy_url(self):
        settings = make_settings()
        with patch("db.async_engine.create_async_engine") as mock_create:
            get_async_engine(settings)
        assert mock_create.call_args.args[0] == settings.sqlalchemy_url

    def test_pool_size_is_min_connections(self):
        with patch("db.async_engine.create_async_engine") as mock_create:
            get_async_engine(make_settings(MIN_CONNECTIONS=3, MAX_CONNECTIONS=10))
        assert mock_create.call_args.kwargs["pool_size"] == 3

    def test_max_overflow_is_difference_between_max_and_min(self):
        with patch("db.async_engine.create_async_engine") as mock_create:
            get_async_engine(make_settings(MIN_CONNECTIONS=3, MAX_CONNECTIONS=10))
        assert mock_create.call_args.kwargs["max_overflow"] == 7

    def test_pool_pre_ping_enabled(self):
        with patch("db.async_engine.create_async_engine") as mock_create:
            get_async_engine(make_settings())
        assert mock_create.call_args.kwargs["pool_pre_ping"] is True

    def test_pool_recycle_is_30_minutes(self):
        with patch("db.async_engine.create_async_engine") as mock_create:
            get_async_engine(make_settings())
        assert mock_create.call_args.kwargs["pool_recycle"] == 1800

    def test_pool_timeout_is_60_seconds(self):
        with patch("db.async_engine.create_async_engine") as mock_create:
            get_async_engine(make_settings())
        assert mock_create.call_args.kwargs["pool_timeout"] == 60


class TestGetSessionFactory:
    def test_returns_async_sessionmaker(self):
        factory = get_session_factory(MagicMock(spec=AsyncEngine))
        assert isinstance(factory, async_sessionmaker)

    def test_expire_on_commit_is_false(self):
        with patch("db.async_engine.async_sessionmaker") as mock_maker:
            get_session_factory(MagicMock(spec=AsyncEngine))
        assert mock_maker.call_args.kwargs["expire_on_commit"] is False

    def test_uses_async_session_class(self):
        from sqlalchemy.ext.asyncio import AsyncSession

        with patch("db.async_engine.async_sessionmaker") as mock_maker:
            get_session_factory(MagicMock(spec=AsyncEngine))
        assert mock_maker.call_args.kwargs["class_"] is AsyncSession


class TestCloseAsyncEngine:
    async def test_calls_dispose_on_engine(self):
        engine = AsyncMock(spec=AsyncEngine)
        await close_async_engine(engine)
        engine.dispose.assert_awaited_once()


class TestCheckConnection:
    async def test_returns_true_when_select_1_returns_1(self):
        result = await check_connection(make_session_factory(scalar_value=1))
        assert result is True

    async def test_returns_false_when_scalar_is_not_1(self):
        result = await check_connection(make_session_factory(scalar_value=0))
        assert result is False

    async def test_executes_select_1(self):
        factory = make_session_factory()
        await check_connection(factory)
        session = factory.return_value.__aenter__.return_value
        call_arg = session.execute.call_args.args[0]
        assert str(call_arg) == "SELECT 1"
