from eval_agent.config import get_settings


def test_기본값으로_설정을_읽는다(monkeypatch):
    # monkeypatch: 테스트 동안만 환경변수를 바꾸고 끝나면 원복해 주는 pytest 내장 픽스처
    monkeypatch.delenv("AGENT_MAX_ITERATIONS", raising=False)
    monkeypatch.setenv("ANTHROPIC_MODEL", "test-model")

    settings = get_settings()

    assert settings.agent_max_iterations == 6
    assert settings.anthropic_model == "test-model"


def test_답변_최대_길이_기본값과_환경변수_override(monkeypatch):
    monkeypatch.delenv("AGENT_MAX_TOKENS", raising=False)
    assert get_settings().agent_max_tokens == 2048

    monkeypatch.setenv("AGENT_MAX_TOKENS", "4096")
    assert get_settings().agent_max_tokens == 4096
