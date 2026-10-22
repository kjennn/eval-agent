"""에이전트 그래프 테스트. 실제 Claude를 부르지 않고, 정해 둔 응답을 차례로 내놓는 가짜 LLM을 쓴다.

가짜 LLM으로 검증하는 것: '그래프의 배선'(도구 호출 → 실행 → 다시 LLM → 최종 답변, 반복 한도, 근거 첨부).
가짜 LLM으로 검증할 수 없는 것: 실제 Claude가 도구를 알맞게 고르는지, 프롬프트 규칙을 지키는지.
후자는 CLI로 실제 질문을 던져서 사람이 확인한다.
"""

import json

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from eval_agent.agent.factory import AgentConfigError, create_agent
from eval_agent.agent.graph import build_graph, format_evidence, message_text, run_agent
from eval_agent.agent.langchain_tools import build_tools
from eval_agent.agent.prompts import build_system_prompt
from eval_agent.config import Settings


class FakeToolLLM(FakeMessagesListChatModel):
    """정해진 응답을 순서대로(끝나면 처음부터) 돌려주는 가짜 LLM. 받은 입력도 기록한다."""

    seen: list = []

    def bind_tools(self, tools, **kwargs):  # 실제 모델은 도구 스키마를 붙이지만 가짜는 그대로 쓴다
        return self

    def _generate(self, messages, *args, **kwargs):
        self.seen.append(messages)
        result = super()._generate(messages, *args, **kwargs)
        # 실제 LLM은 호출할 때마다 새 메시지(새 id)를 돌려준다. 가짜가 같은 객체를 재사용하면
        # LangGraph의 add_messages가 '같은 id = 기존 메시지 교체'로 처리해서 기록이 늘지 않으므로 복사본을 준다.
        return ChatResult(
            generations=[
                ChatGeneration(message=g.message.model_copy(update={"id": None}))
                for g in result.generations
            ]
        )


def tool_call(name: str, args: dict, call_id: str = "call_1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


def make_agent(session_factory, responses, max_iterations: int = 6):
    llm = FakeToolLLM(responses=responses)
    llm.seen = []
    graph = build_graph(llm, build_tools(session_factory), "테스트 프롬프트", max_iterations)
    return llm, graph


SALES_2025 = {"year": 2025, "org_name": "영업본부", "eval_type": "성과"}


def test_도구를_호출하고_결과를_본_뒤_최종_답변을_한다(session_factory):
    llm, graph = make_agent(
        session_factory,
        [tool_call("get_grade_distribution", SALES_2025), AIMessage(content="영업본부 B등급은 68.3%입니다.")],
    )
    state = run_agent(graph, "영업본부 2025 성과 B등급 비율은?", 6)

    kinds = [type(m).__name__ for m in state["messages"]]
    assert kinds == ["HumanMessage", "AIMessage", "ToolMessage", "AIMessage"]
    tool_result = json.loads(state["messages"][2].content)
    assert tool_result["total"] == 60  # 가짜 LLM이 요청한 도구가 진짜 DB에 대해 실행됐다
    assert next(d["count"] for d in tool_result["distribution"] if d["grade"] == "B") == 41
    assert state["iterations"] == 2
    assert state["answer"].startswith("영업본부 B등급은 68.3%입니다.")


def test_답변_끝에_실제_호출_기록으로_근거가_붙는다(session_factory):
    _, graph = make_agent(
        session_factory,
        [tool_call("get_grade_distribution", SALES_2025), AIMessage(content="답변")],
    )
    answer = run_agent(graph, "질문", 6)["answer"]
    assert "근거(호출한 도구와 조건):" in answer
    assert "- get_grade_distribution(year=2025, org_name='영업본부', eval_type='성과')" in answer


def test_도구를_부르지_않으면_근거에_그렇게_표시한다(session_factory):
    _, graph = make_agent(session_factory, [AIMessage(content="평가와 무관한 질문입니다.")])
    answer = run_agent(graph, "오늘 날씨는?", 6)["answer"]
    assert answer.endswith("근거: 도구를 호출하지 않았습니다.")


def test_반복_한도에_도달하면_멈추고_추가확인을_안내한다(session_factory):
    # 가짜 LLM이 매번 도구만 요청한다 = 무한 루프 상황
    _, graph = make_agent(
        session_factory, [tool_call("get_grade_distribution", SALES_2025)], max_iterations=3
    )
    state = run_agent(graph, "질문", 3)

    assert state["iterations"] == 3
    tool_messages = [m for m in state["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 2  # 1, 2회차는 도구를 실행했고 3회차는 한도라서 실행하지 않고 멈췄다
    assert "반복 한도(3회)" in state["answer"]
    assert "추가 확인이 필요합니다" in state["answer"]


def test_데이터_없음_결과는_근거에_오류로_표시된다(session_factory):
    _, graph = make_agent(
        session_factory,
        [tool_call("get_grade_distribution", {"year": 2023}), AIMessage(content="2023년 데이터는 없습니다.")],
    )
    state = run_agent(graph, "2023년 결과 보여줘", 6)
    assert json.loads(state["messages"][2].content)["error"] == "no_data"
    assert "- get_grade_distribution(year=2023) → 오류: no_data" in state["answer"]


def test_같은_조건의_중복_호출은_근거에_한_번만_나온다(session_factory):
    _, graph = make_agent(
        session_factory,
        [
            tool_call("get_grade_distribution", SALES_2025, "c1"),
            tool_call("get_grade_distribution", SALES_2025, "c2"),
            AIMessage(content="답변"),
        ],
    )
    answer = run_agent(graph, "질문", 6)["answer"]
    assert answer.count("get_grade_distribution(") == 1


def test_LLM_호출_맨_앞에_시스템_프롬프트가_붙는다(session_factory):
    llm, graph = make_agent(session_factory, [AIMessage(content="답변")])
    run_agent(graph, "질문입니다", 6)
    first_call = llm.seen[0]
    assert isinstance(first_call[0], SystemMessage) and first_call[0].content == "테스트 프롬프트"
    assert isinstance(first_call[1], HumanMessage) and first_call[1].content == "질문입니다"


def test_on_message_콜백은_새_메시지마다_한_번씩_호출된다(session_factory):
    _, graph = make_agent(
        session_factory,
        [tool_call("get_org_summary", {"year": 2025, "org_name": "개발본부"}), AIMessage(content="답변")],
    )
    seen = []
    run_agent(graph, "질문", 6, on_message=seen.append)
    assert [type(m).__name__ for m in seen] == ["HumanMessage", "AIMessage", "ToolMessage", "AIMessage"]


# ---------- 보조 함수 / 도구 래퍼 / 프롬프트 / 설정 ----------


def test_message_text는_문자열과_블록목록을_모두_처리한다():
    assert message_text(AIMessage(content="안녕")) == "안녕"
    blocks = [{"type": "text", "text": "가"}, {"type": "tool_use", "id": "x"}, {"type": "text", "text": "나"}]
    assert message_text(AIMessage(content=blocks)) == "가나"


def test_format_evidence는_None_인자를_생략한다():
    msgs = [tool_call("get_grade_distribution", {"year": 2025, "org_name": None, "eval_type": None})]
    assert "- get_grade_distribution(year=2025)" in format_evidence(msgs)


def test_도구_래퍼는_4개이고_이름과_설명이_있다(session_factory):
    tools = build_tools(session_factory)
    assert [t.name for t in tools] == [
        "get_grade_distribution", "compare_years", "get_org_summary", "search_policy_docs",
    ]
    assert all(len(t.description) > 20 for t in tools)
    # LLM에게 보이는 파라미터 스키마가 3단계 함수 시그니처와 같다
    assert set(tools[1].args) == {"org_name", "year_from", "year_to"}


def test_도구_래퍼를_호출하면_JSON_문자열이_돌아온다(session_factory):
    tools = {t.name: t for t in build_tools(session_factory)}
    out = tools["compare_years"].invoke({"org_name": "영업본부", "year_from": 2024, "year_to": 2025})
    assert isinstance(out, str)
    assert json.loads(out)["org_name"] == "영업본부"
    assert json.loads(tools["search_policy_docs"].invoke({"query": "영업본부 B등급"}))["found"] is True


def test_시스템_프롬프트에_조회_가능_연도와_핵심_규칙이_들어_있다():
    prompt = build_system_prompt([2024, 2025])
    assert "2024, 2025" in prompt
    for rule in ["추가 확인이 필요합니다", "개인의 이름", "unit 필드", "자동으로 붙입니다"]:
        assert rule in prompt


@pytest.mark.parametrize(
    "key, model, expected",
    [("", "m", "ANTHROPIC_API_KEY"), ("k", "", "ANTHROPIC_MODEL")],
)
def test_API_키나_모델명이_없으면_설정_오류다(key, model, expected):
    settings = Settings("sqlite://", key, model, 6)
    with pytest.raises(AgentConfigError, match=expected):
        create_agent(settings)
