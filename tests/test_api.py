"""FastAPI 테스트. TestClient는 서버를 띄우지 않고 앱을 메모리에서 직접 호출한다. (Spring의 MockMvc와 비슷)

`with TestClient(app) as client:` 처럼 with로 열어야 lifespan(서버 시작/종료 구간)이 실행된다.
"""

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from eval_agent.agent.factory import AgentConfigError, EvalAgent
from eval_agent.agent.graph import build_graph
from eval_agent.agent.langchain_tools import build_tools
from eval_agent.api.app import create_app
from tests.test_agent_graph import FakeToolLLM, tool_call


class StubAgent:
    """에이전트 자리에 꽂는 가짜. 정해진 상태를 돌려주거나 예외를 던진다."""

    def __init__(self, state=None, error: Exception | None = None):
        self.state, self.error, self.questions = state, error, []

    def ask(self, question, on_message=None):
        self.questions.append(question)
        if self.error:
            raise self.error
        return self.state


STATE = {
    "question": "q",
    "messages": [
        HumanMessage("q"),
        AIMessage(content="", tool_calls=[{"name": "get_org_summary", "args": {"year": 2025, "org_name": "개발본부"}, "id": "c1", "type": "tool_call"}]),
    ],
    "iterations": 2,
    "answer": "개발본부 다면평가 평균은 76.66입니다.\n\n근거(호출한 도구와 조건):\n- get_org_summary(year=2025, org_name='개발본부')",
}


def client_for(agent):
    return TestClient(create_app(agent=agent))


def test_ask는_답변과_도구호출_목록과_반복횟수를_돌려준다():
    agent = StubAgent(STATE)
    with client_for(agent) as client:
        res = client.post("/ask", json={"question": "개발본부 다면평가 평균은?"})

    assert res.status_code == 200
    body = res.json()
    assert body["answer"].startswith("개발본부 다면평가 평균은 76.66입니다.")
    assert body["tool_calls"] == [
        {"name": "get_org_summary", "args": {"year": 2025, "org_name": "개발본부"}, "error": None}
    ]
    assert body["iterations"] == 2
    assert agent.questions == ["개발본부 다면평가 평균은?"]


def test_질문_앞뒤_공백은_잘라서_에이전트에_전달한다():
    agent = StubAgent(STATE)
    with client_for(agent) as client:
        assert client.post("/ask", json={"question": "  질문입니다  "}).status_code == 200
    assert agent.questions == ["질문입니다"]


@pytest.mark.parametrize(
    "payload",
    [
        {},  # question 없음
        {"question": ""},  # 빈 문자열
        {"question": "   "},  # 공백뿐
        {"question": "가" * 501},  # 상한(500자) 초과
        {"question": 123},  # 문자열이 아님
    ],
)
def test_잘못된_입력은_422이고_에이전트를_호출하지_않는다(payload):
    agent = StubAgent(STATE)
    with client_for(agent) as client:
        assert client.post("/ask", json=payload).status_code == 422
    assert agent.questions == []  # 비용이 드는 LLM 호출까지 가지 않았다


def test_500자_질문은_허용된다():
    with client_for(StubAgent(STATE)) as client:
        assert client.post("/ask", json={"question": "가" * 500}).status_code == 200


def test_에이전트_실행이_실패하면_502이고_내부_원인은_응답에_노출하지_않는다():
    secret = "invalid x-api-key sk-ant-SECRET"
    with client_for(StubAgent(error=RuntimeError(secret))) as client:
        res = client.post("/ask", json={"question": "질문"})
    assert res.status_code == 502
    assert "LLM 호출 중 오류" in res.json()["detail"]
    assert secret not in res.text and "sk-ant" not in res.text


def test_health와_openapi_문서가_있다():
    with client_for(StubAgent(STATE)) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert "/ask" in client.get("/openapi.json").json()["paths"]


def test_설정이_없으면_서버_시작_단계에서_실패한다(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    with pytest.raises(AgentConfigError, match="ANTHROPIC_API_KEY"):
        with TestClient(create_app()):  # agent를 주지 않으면 lifespan에서 설정으로 에이전트를 만든다
            pass


def test_HTTP부터_도구_실행까지_통합_흐름(session_factory):
    # 가짜 LLM + 진짜 도구 + 진짜(메모리) DB. LLM만 가짜다.
    llm = FakeToolLLM(responses=[
        tool_call("get_grade_distribution", {"year": 2025, "org_name": "영업본부", "eval_type": "성과"}),
        AIMessage(content="영업본부 2025년 성과평가 B등급은 68.3%입니다."),
    ])
    llm.seen = []
    agent = EvalAgent(build_graph(llm, build_tools(session_factory), "프롬프트", 6), 6)

    with client_for(agent) as client:
        body = client.post("/ask", json={"question": "영업본부 2025 성과 B등급 비율은?"}).json()

    assert body["answer"].startswith("영업본부 2025년 성과평가 B등급은 68.3%입니다.")
    assert "- get_grade_distribution(year=2025, org_name='영업본부', eval_type='성과')" in body["answer"]
    assert body["tool_calls"] == [
        {"name": "get_grade_distribution", "args": {"year": 2025, "org_name": "영업본부", "eval_type": "성과"}, "error": None}
    ]
    assert body["iterations"] == 2


def test_도구_오류는_tool_calls의_error로_내려간다(session_factory):
    llm = FakeToolLLM(responses=[
        tool_call("get_grade_distribution", {"year": 2023}),
        AIMessage(content="2023년 데이터는 없습니다."),
    ])
    llm.seen = []
    agent = EvalAgent(build_graph(llm, build_tools(session_factory), "프롬프트", 6), 6)
    with client_for(agent) as client:
        body = client.post("/ask", json={"question": "2023년 결과 보여줘"}).json()
    assert body["tool_calls"][0]["error"] == "no_data"
