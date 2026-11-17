"""Generated deployment secrets: created once, never replaced, read from files, enforced in production."""

import stat

import pytest

from core.config import DEV_SECRET, Settings, get_settings
from pipelines import init_secrets


def test_secrets_are_created_once_and_agree(tmp_path, capsys):
    target = tmp_path / "secrets"
    assert init_secrets.ensure(target) == ["db_password", "aurex_database_password", "aurex_secret_key"]
    files = {p.name: p for p in target.iterdir()}
    password = files["db_password"].read_text()
    assert len(password) == 48 and files["aurex_database_password"].read_text() == password
    assert len(files["aurex_secret_key"].read_text()) == 64
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o400 for p in files.values())

    before = {name: p.read_text() for name, p in files.items()}
    init_secrets.main([str(target)])  # a restart changes nothing and prints no value
    output = capsys.readouterr().out
    assert "none, all present" in output and all(value not in output for value in before.values())
    assert {name: p.read_text() for name, p in files.items()} == before


def test_a_lost_application_copy_is_restored_from_the_database_password(tmp_path):
    init_secrets.ensure(tmp_path)
    password = (tmp_path / "db_password").read_text()
    (tmp_path / "aurex_database_password").unlink()
    assert init_secrets.ensure(tmp_path) == ["aurex_database_password"]
    assert (tmp_path / "aurex_database_password").read_text() == password


def test_settings_read_secret_files_and_put_the_password_into_the_url(tmp_path, monkeypatch):
    init_secrets.ensure(tmp_path)
    monkeypatch.delenv("AUREX_SECRET_KEY", raising=False)
    monkeypatch.delenv("AUREX_DATABASE_PASSWORD", raising=False)
    monkeypatch.setenv("AUREX_DATABASE_URL", "postgresql+psycopg://aurex@db:5432/aurex")
    monkeypatch.setenv("AUREX_SECRETS_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        settings = get_settings()
        password = (tmp_path / "aurex_database_password").read_text()
        assert settings.secret_key == (tmp_path / "aurex_secret_key").read_text()
        assert settings.database_url == f"postgresql+psycopg://aurex:{password}@db:5432/aurex"
        monkeypatch.setenv("AUREX_SECRET_KEY", "from-the-environment")  # the environment wins over files
        get_settings.cache_clear()
        assert get_settings().secret_key == "from-the-environment"
    finally:
        get_settings.cache_clear()


def test_production_requires_a_secret_and_an_https_address():
    safe = {"environment": "production", "secret_key": "s" * 64, "public_url": "https://aurex.example.com"}
    Settings(**safe).assert_safe()
    Settings(environment="development").assert_safe()  # local defaults are fine outside production
    with pytest.raises(RuntimeError, match="AUREX_SECRET_KEY"):
        Settings(**{**safe, "secret_key": DEV_SECRET}).assert_safe()
    with pytest.raises(RuntimeError, match="AUREX_PUBLIC_URL"):
        Settings(**{**safe, "public_url": "http://localhost:3000"}).assert_safe()
