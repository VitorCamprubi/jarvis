from pathlib import Path

import pytest

from jarvis import paths
from jarvis.config import ConfigError, load_config, load_secrets
from jarvis.config.loader import DEFAULT_FILE, LOCAL_FILE, deep_merge


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """An isolated directory holding a copy of the shipped default.toml."""
    shipped = (paths.CONFIG_DIR / DEFAULT_FILE).read_text(encoding="utf-8")
    (tmp_path / DEFAULT_FILE).write_text(shipped, encoding="utf-8")
    return tmp_path


def write_local(config_dir: Path, toml: str) -> None:
    (config_dir / LOCAL_FILE).write_text(toml, encoding="utf-8")


def test_shipped_defaults_are_valid(config_dir: Path) -> None:
    config = load_config(config_dir)

    assert config.weather.city == "Sorocaba"
    assert config.weather.region == "SP"


def test_local_file_overrides_only_the_keys_it_sets(config_dir: Path) -> None:
    defaults = load_config(config_dir)
    write_local(config_dir, '[logging]\nlevel = "DEBUG"\n')

    config = load_config(config_dir)

    assert config.logging.level == "DEBUG"
    assert config.logging.model_dump(exclude={"level"}) == defaults.logging.model_dump(
        exclude={"level"}
    )
    assert config.weather == defaults.weather


def test_unknown_key_is_rejected(config_dir: Path) -> None:
    write_local(config_dir, '[logging]\nlevle = "DEBUG"\n')

    with pytest.raises(ConfigError, match="levle"):
        load_config(config_dir)


@pytest.mark.parametrize(
    "toml",
    [
        '[logging]\nlevel = "LOUD"\n',
        "[logging]\nmax_file_size_mb = 0\n",
        "[weather]\nlatitude = 123.0\n",
        '[weather]\ncountry_code = "brazil"\n',
    ],
)
def test_invalid_values_are_rejected(config_dir: Path, toml: str) -> None:
    write_local(config_dir, toml)

    with pytest.raises(ConfigError, match="Invalid configuration"):
        load_config(config_dir)


def test_missing_default_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path)


def test_malformed_toml_is_reported(config_dir: Path) -> None:
    write_local(config_dir, "[logging\n")

    with pytest.raises(ConfigError, match="Malformed TOML"):
        load_config(config_dir)


def test_deep_merge_merges_tables_and_replaces_other_values() -> None:
    base = {"table": {"x": 1, "y": 2}, "items": [1, 2], "keep": "v"}
    override = {"table": {"y": 3}, "items": [9]}

    merged = deep_merge(base, override)

    assert merged == {"table": {"x": 1, "y": 3}, "items": [9], "keep": "v"}
    assert base == {"table": {"x": 1, "y": 2}, "items": [1, 2], "keep": "v"}


def test_secrets_are_read_from_env_file_and_masked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=test-key-123\n", encoding="utf-8")

    secrets = load_secrets(env_file)

    assert secrets.anthropic_api_key is not None
    assert secrets.anthropic_api_key.get_secret_value() == "test-key-123"
    assert "test-key-123" not in repr(secrets)


def test_missing_env_file_means_no_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    assert load_secrets(tmp_path / ".env").anthropic_api_key is None
