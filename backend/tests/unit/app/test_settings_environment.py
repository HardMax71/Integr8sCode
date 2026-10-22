import pytest

from app.settings import Settings

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(("env_value", "expected"), [("production", "production"), ("", "test")])
def test_environment_comes_from_the_env_before_the_toml(
    monkeypatch: pytest.MonkeyPatch, env_value: str, expected: str
) -> None:
    monkeypatch.setenv("ENVIRONMENT", env_value)

    assert Settings(config_path="config.test.toml").ENVIRONMENT == expected
