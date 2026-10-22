from eval_agent.config import get_settings


def test_기본값으로_설정을_읽는다(monkeypatch):
    # monkeypatch: 테스트 동안만 환경변수를 바꾸고 끝나면 원복해 주는 pytest 내장 픽스처
    monkeypatch.delenv("AGENT_MAX_ITERATIONS", raising=False)
    monkeypatch.setenv("ANTHROPIC_MODEL", "test-model")

    settings = get_settings()

    assert settings.agent_max_iterations == 6
    assert settings.anthropic_model == "test-model"
