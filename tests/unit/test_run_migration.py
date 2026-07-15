"""
Unit tests for scripts/ci/run_migration.py.
All database and Alembic calls are mocked — no real DB connection needed.
"""
from __future__ import annotations

import json
import os
from io import StringIO
from unittest.mock import MagicMock, patch, call

import pytest

import scripts.ci.run_migration as runner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _capture_logs(capsys: pytest.CaptureFixture[str]) -> list[dict]:
    """Parse all stdout JSON log lines emitted by the runner."""
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.strip().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# _log
# ---------------------------------------------------------------------------

class TestLog:
    def test_emits_json_with_event_and_timestamp(self, capsys: pytest.CaptureFixture[str]) -> None:
        runner._log("test_event", key="value")
        logs = _capture_logs(capsys)
        assert len(logs) == 1
        assert logs[0]["event"] == "test_event"
        assert logs[0]["key"] == "value"
        assert "timestamp" in logs[0]

    def test_extra_kwargs_present(self, capsys: pytest.CaptureFixture[str]) -> None:
        runner._log("e", revision="0020", duration_ms=42)
        logs = _capture_logs(capsys)
        assert logs[0]["revision"] == "0020"
        assert logs[0]["duration_ms"] == 42


# ---------------------------------------------------------------------------
# main() — missing DATABASE_URL
# ---------------------------------------------------------------------------

class TestMainMissingDatabaseUrl:
    def test_returns_1_when_no_database_url(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        result = runner.main()
        assert result == 1
        logs = _capture_logs(capsys)
        assert any(l["event"] == "migration_error" for l in logs)
        assert any("DATABASE_URL" in str(l.get("error", "")) for l in logs)


# ---------------------------------------------------------------------------
# main() — DB connection failure
# ---------------------------------------------------------------------------

class TestMainDbConnectionFailure:
    def test_returns_1_on_connection_error(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
        with patch("scripts.ci.run_migration.create_engine") as mock_engine:
            mock_engine.return_value.connect.side_effect = Exception("connection refused")
            result = runner.main()
        assert result == 1
        logs = _capture_logs(capsys)
        assert any(l["event"] == "migration_error" and l.get("phase") == "db_connect" for l in logs)


# ---------------------------------------------------------------------------
# main() — successful migration
# ---------------------------------------------------------------------------

class TestMainSuccessfulMigration:
    def test_returns_0_on_success(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "DATABASE_URL",
            "postgresql+asyncpg://u:p@localhost:5432/contextiq",
        )
        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_ctx = MagicMock()
        mock_ctx.get_current_revision.side_effect = ["0019", "0020"]

        with patch("scripts.ci.run_migration.create_engine", return_value=mock_engine), \
             patch("scripts.ci.run_migration.MigrationContext") as mock_mctx_cls, \
             patch("scripts.ci.run_migration.command") as mock_cmd, \
             patch("scripts.ci.run_migration.Config"):
            mock_mctx_cls.configure.return_value = mock_ctx
            result = runner.main()

        assert result == 0
        mock_cmd.upgrade.assert_called_once_with(mock_cmd.upgrade.call_args[0][0], "head")
        logs = _capture_logs(capsys)
        assert any(l["event"] == "migration_succeeded" for l in logs)
        succeeded = next(l for l in logs if l["event"] == "migration_succeeded")
        assert succeeded["previous_revision"] == "0019"
        assert succeeded["current_revision"] == "0020"
        assert isinstance(succeeded["duration_ms"], int)

    def test_logs_current_revision_before_migration(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@host/db")
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_ctx = MagicMock()
        mock_ctx.get_current_revision.return_value = "0019"

        with patch("scripts.ci.run_migration.create_engine", return_value=mock_engine), \
             patch("scripts.ci.run_migration.MigrationContext") as mock_mctx_cls, \
             patch("scripts.ci.run_migration.command"), \
             patch("scripts.ci.run_migration.Config"):
            mock_mctx_cls.configure.return_value = mock_ctx
            runner.main()

        logs = _capture_logs(capsys)
        assert any(l["event"] == "migration_current_revision" and l["revision"] == "0019" for l in logs)


# ---------------------------------------------------------------------------
# main() — migration failure
# ---------------------------------------------------------------------------

class TestMainMigrationFailure:
    def test_returns_1_and_logs_error_on_alembic_failure(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@host/db")
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_ctx = MagicMock()
        mock_ctx.get_current_revision.return_value = "0019"

        with patch("scripts.ci.run_migration.create_engine", return_value=mock_engine), \
             patch("scripts.ci.run_migration.MigrationContext") as mock_mctx_cls, \
             patch("scripts.ci.run_migration.command") as mock_cmd, \
             patch("scripts.ci.run_migration.Config"):
            mock_mctx_cls.configure.return_value = mock_ctx
            mock_cmd.upgrade.side_effect = Exception("column already exists")
            result = runner.main()

        assert result == 1
        logs = _capture_logs(capsys)
        assert any(l["event"] == "migration_failed" for l in logs)
        failed = next(l for l in logs if l["event"] == "migration_failed")
        assert "column already exists" in failed["error"]
        assert failed["current_revision"] == "0019"

    def test_no_migration_succeeded_log_on_failure(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@host/db")
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        with patch("scripts.ci.run_migration.create_engine", return_value=mock_engine), \
             patch("scripts.ci.run_migration.MigrationContext") as mock_mctx_cls, \
             patch("scripts.ci.run_migration.command") as mock_cmd, \
             patch("scripts.ci.run_migration.Config"):
            mock_mctx_cls.configure.return_value = MagicMock()
            mock_cmd.upgrade.side_effect = Exception("syntax error")
            runner.main()

        logs = _capture_logs(capsys)
        assert not any(l["event"] == "migration_succeeded" for l in logs)


# ---------------------------------------------------------------------------
# URL sanitisation (asyncpg → psycopg2)
# ---------------------------------------------------------------------------

class TestUrlConversion:
    def test_asyncpg_url_converted_to_sync(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "DATABASE_URL",
            "postgresql+asyncpg://user:pass@pg-host:5432/mydb",
        )
        captured_urls: list[str] = []

        def fake_create_engine(url: str, **kwargs: object) -> MagicMock:
            captured_urls.append(url)
            raise Exception("stop after url capture")

        with patch("scripts.ci.run_migration.create_engine", side_effect=fake_create_engine):
            runner.main()

        assert captured_urls, "create_engine was never called"
        assert captured_urls[0].startswith("postgresql://"), (
            f"Expected sync URL, got: {captured_urls[0]!r}"
        )
        assert "asyncpg" not in captured_urls[0]
