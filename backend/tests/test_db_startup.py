from __future__ import annotations

import pytest


def _fake_head(monkeypatch, head, version, *, table_exists=True):
    import app.main as main_module

    def _head_and_current():
        return head, version

    monkeypatch.setattr(main_module, "_alembic_head_and_current", _head_and_current)


def test_db_auto_create_flag_default(monkeypatch):
    from app.core.config import settings

    assert settings.db_auto_create is True


def test_prod_fail_fast_when_behind_head(monkeypatch):
    from app.main import _init_database

    monkeypatch.setattr("app.main.settings.db_auto_create", False)
    _fake_head(monkeypatch, head="aaa", version="bbb")

    with pytest.raises(RuntimeError, match="Схема БД не соответствует миграциям"):
        _init_database()


def test_prod_ok_when_on_head(monkeypatch, caplog):
    from app.main import _init_database

    monkeypatch.setattr("app.main.settings.db_auto_create", False)
    _fake_head(monkeypatch, head="a1b2c3d4e5fe", version="a1b2c3d4e5fe")

    with caplog.at_level("INFO", logger="agentforge"):
        _init_database()
    assert any(
        "База готова (Alembic)" in r.getMessage() for r in caplog.records
    )


def test_prod_fail_fast_when_no_migrations(monkeypatch):
    from app.main import _init_database

    monkeypatch.setattr("app.main.settings.db_auto_create", False)
    _fake_head(monkeypatch, head=None, version=None)

    with pytest.raises(RuntimeError, match="Миграции не найдены"):
        _init_database()


def test_dev_warns_when_db_behind_head(monkeypatch, caplog):
    from app.main import _init_database

    monkeypatch.setattr("app.main.settings.db_auto_create", True)
    monkeypatch.setattr("app.main.Base.metadata.create_all", lambda bind: None)

    def _fake_seed(db):
        return {
            "company": True, "system_agent": True, "email_agent": True,
            "search_agent": True, "knowledge": True, "admin": True,
        }

    import app.core.seeding as seeding

    monkeypatch.setattr(seeding, "seed_demo", _fake_seed)
    _fake_head(monkeypatch, head="aaa", version="bbb")

    with caplog.at_level("WARNING", logger="agentforge"):
        _init_database()
    assert any("отстаёт от миграций" in r.getMessage() for r in caplog.records)
