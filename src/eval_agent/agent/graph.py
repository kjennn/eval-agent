"""LangGraph 에이전트: 상태, 노드, 흐름.

흐름
                 ┌──────────── 도구 호출 요청 있음 & 한도 미만 ───────────┐
                 ▼                                                        │
    START → [agent] ──┬── 도구 호출 요청 없음 ──→ [finalize] → END         │
                      ├── 도구 호출 요청 있음 & 한도 도달 → [limit] → END   │
                      └───────────────→ [tools] ───────────────────────────┘
                                         (도구 실행 후 다시 agent로)

- agent: LLM을 한 번 호출한다. LLM은 "도구를 부르겠다"(tool_calls) 또는 "최종 답변"을 돌려준다.
- tools: LLM이 요청한 도구를 실제로 실행하고, 결과를 ToolMessage로 상태에 쌓는다.
- finalize: 최종 답변 뒤에 '근거(어떤 도구를 어떤 조건으로 불렀는지)'를 코드로 붙인다.
- limit: 반복 한도에 도달하면 무한 루프 대신 여기서 멈춘다.

Spring 비교: 워크플로(이전 프로젝트)는 "A → B → C"를 코드가 고정하지만, 여기서는
다음에 어느 노드로 갈지를 LLM의 응답(tool_calls 유무)이 결정한다. route()가 그 분기점이다.

새 문법 메모
- TypedDict: 키와 값 타입이 정해진 dict. Java의 record처럼 '모양'만 정의한다. (런타임 검사는 없다)
- Annotated[타입, 리듀서]: "이 필드를 갱신할 때 새 값으로 덮어쓰지 말고 리듀서로 합쳐라"는 표시.
  add_messages는 '기존 메시지 목록 뒤에 이어 붙이는' 리듀서다. 노드는 상태 전체가 아니라 '바뀐 부분만'
  dict로 돌려주고, LangGraph가 상태에 병합한다.
"""

import json
from collections.abc import Callable
from typing import Annotated, Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode


class AgentState(TypedDict):
    question: str  # 사용자의 질문
    messages: Annotated[list[AnyMessage], add_messages]  # 대화/도구 호출 기록 (도구 결과 포함)
    iterations: int  # agent 노드를 몇 번 실행했는가 (무한 루프 방지용 카운터)
    answer: str  # 사용자에게 보여줄 최종 답변 (근거 포함)


# ---------- 메시지 → 텍스트/근거 변환 (순수 함수라서 따로 테스트할 수 있다) ----------


def message_text(message: BaseMessage) -> str:
    """Anthropic 응답은 content가 문자열이거나 [{'type': 'text', 'text': ...}] 블록 목록이다."""
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )


def _was_truncated(message: BaseMessage) -> bool:
    """Anthropic은 답변이 max_tokens에 걸려 끊기면 응답 메타데이터의 stop_reason에 'max_tokens'를 담아 준다."""
    metadata = getattr(message, "response_metadata", None) or {}
    return metadata.get("stop_reason") == "max_tokens"


def _error_of(tool_content: Any) -> str | None:
    """도구 결과가 에러면 그 코드를 돌려준다. (3단계 도구는 {"error": "no_data", ...} 형태로 알린다)"""
    if not isinstance(tool_content, str):
        return None
    if tool_content.startswith("Error"):  # 도구 실행 중 예외가 난 경우 ToolNode가 이렇게 알려 준다
        return "tool_execution_error"
    try:
        parsed = json.loads(tool_content)
    except json.JSONDecodeError:
        return None
    return str(parsed["error"]) if isinstance(parsed, dict) and "error" in parsed else None


def collect_tool_calls(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    """메시지 기록에서 실제로 일어난 도구 호출을 뽑는다: [{"name", "args", "error"}].

    같은 조건의 중복 호출은 한 번만 담고, 값이 None인 인자는 뺀다.
    error는 도구 결과가 에러였을 때만 코드(예: "no_data")가 들어가고 아니면 None이다.
    """
    results = {m.tool_call_id: m.content for m in messages if isinstance(m, ToolMessage)}
    seen: set[tuple[str, str]] = set()
    calls: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        for call in message.tool_calls:
            args = {k: v for k, v in call["args"].items() if v is not None}
            key = (call["name"], json.dumps(args, sort_keys=True, ensure_ascii=False))
            if key in seen:
                continue
            seen.add(key)
            calls.append({"name": call["name"], "args": args, "error": _error_of(results.get(call["id"]))})
    return calls


def format_evidence(messages: list[BaseMessage]) -> str:
    """실제로 일어난 도구 호출 기록에서 '근거' 문구를 만든다.

    LLM에게 "근거를 써 줘"라고 시키지 않고 코드가 직접 만드는 이유:
    LLM은 호출하지 않은 도구를 호출했다고 쓰거나 조건을 틀리게 쓸 수 있다. 기록에서 뽑으면 사실만 남는다.
    """
    calls = collect_tool_calls(messages)
    if not calls:
        return "근거: 도구를 호출하지 않았습니다."
    lines = []
    for call in calls:
        arg_text = ", ".join(f"{k}={v!r}" for k, v in call["args"].items())
        line = f"- {call['name']}({arg_text})"
        if call["error"]:
            line += f" → 오류: {call['error']}"
        lines.append(line)
    return "근거(호출한 도구와 조건):\n" + "\n".join(lines)


# ---------- 그래프 조립 ----------


def build_graph(
    llm: BaseChatModel,
    tools: list[BaseTool],
    system_prompt: str,
    max_iterations: int,
):
    """에이전트 그래프를 만든다. llm을 밖에서 받으므로 테스트에서는 가짜 LLM을 꽂을 수 있다."""
    llm_with_tools = llm.bind_tools(tools)  # LLM에게 '쓸 수 있는 도구 목록'을 알려 준다

    def agent_node(state: AgentState) -> dict[str, Any]:
        # 시스템 프롬프트는 상태에 저장하지 않고 호출할 때마다 맨 앞에 붙인다.
        response = llm_with_tools.invoke([SystemMessage(system_prompt), *state["messages"]])
        return {"messages": [response], "iterations": state["iterations"] + 1}

    def route(state: AgentState) -> str:
        last = state["messages"][-1]
        if not getattr(last, "tool_calls", None):
            return "finalize"  # 도구 요청이 없다 = LLM이 최종 답변을 했다
        if state["iterations"] >= max_iterations:
            return "limit"  # 도구를 또 부르려 하지만 한도에 도달했다
        return "tools"

    def finalize_node(state: AgentState) -> dict[str, Any]:
        last = state["messages"][-1]
        text = message_text(last).strip()
        if _was_truncated(last):
            # 길이 제한에 걸려 답변이 중간에 끊겼다. 끊긴 문장을 완성된 답변처럼 보여 주지 않고 사실을 알린다.
            text += "\n\n※ 답변이 길이 제한(max_tokens)에 걸려 중간에 잘렸습니다. 질문을 나누어 다시 묻거나 AGENT_MAX_TOKENS를 늘려 주세요."
        return {"answer": f"{text}\n\n{format_evidence(state['messages'])}"}

    def limit_node(state: AgentState) -> dict[str, Any]:
        text = (
            f"분석 반복 한도({max_iterations}회)에 도달해 답변을 완성하지 못했습니다. "
            "추가 확인이 필요합니다."
        )
        return {"answer": f"{text}\n\n{format_evidence(state['messages'])}"}

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(tools))  # 미리 만들어진 도구 실행 노드 (요청된 도구를 실행)
    graph.add_node("finalize", finalize_node)
    graph.add_node("limit", limit_node)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent", route, {"tools": "tools", "finalize": "finalize", "limit": "limit"}
    )
    graph.add_edge("tools", "agent")  # 도구를 실행한 뒤에는 항상 LLM에게 결과를 보여 주러 돌아간다
    graph.add_edge("finalize", END)
    graph.add_edge("limit", END)
    return graph.compile()


def run_agent(
    graph,
    question: str,
    max_iterations: int,
    on_message: Callable[[BaseMessage], None] | None = None,
) -> AgentState:
    """질문 하나를 그래프에 넣고 끝까지 실행한다. on_message를 주면 새 메시지가 생길 때마다 알려 준다."""
    initial: AgentState = {
        "question": question,
        "messages": [HumanMessage(question)],
        "iterations": 0,
        "answer": "",
    }
    # LangGraph 자체의 안전장치(recursion_limit)가 우리 한도보다 먼저 터지지 않도록 넉넉히 잡는다.
    config = {"recursion_limit": max_iterations * 2 + 6}
    final: AgentState = initial
    printed = 0
    # stream_mode="values": 노드가 하나 끝날 때마다 '그 시점의 상태 전체'를 내보낸다.
    for state in graph.stream(initial, config, stream_mode="values"):
        if on_message:
            for message in state["messages"][printed:]:
                on_message(message)
        printed = len(state["messages"])
        final = state
    return final
