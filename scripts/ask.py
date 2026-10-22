"""CLI에서 에이전트에게 질문하기.

    uv run python scripts/ask.py "2025년 본부별 B등급 비율을 비교해줘"
    uv run python scripts/ask.py -v "개발본부 다면평가 평균은?"    # -v: 에이전트가 무엇을 하는지 단계별로 출력
    uv run python scripts/ask.py                                    # 질문 없이 실행하면 대화형 (빈 줄이면 종료)

주의: 질문마다 독립적으로 실행된다. 이전 질문을 기억하지 않는다.
"""

import argparse
import sys

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from eval_agent.agent.factory import AgentConfigError, create_agent
from eval_agent.agent.graph import message_text


def print_step(message: BaseMessage) -> None:
    """--verbose용: 에이전트 루프에서 일어나는 일을 한 줄씩 보여 준다."""
    if isinstance(message, HumanMessage):
        return
    if isinstance(message, AIMessage):
        for call in message.tool_calls:
            print(f"[도구 호출] {call['name']} {call['args']}")
        text = message_text(message).strip()
        if text and not message.tool_calls:
            print("[LLM 최종 응답 생성]")
    elif isinstance(message, ToolMessage):
        content = str(message.content)
        print(f"[도구 결과] {content[:300]}{'...' if len(content) > 300 else ''}")


def main() -> int:
    parser = argparse.ArgumentParser(description="평가 결과 분석 에이전트")
    parser.add_argument("question", nargs="?", help="질문 (생략하면 대화형)")
    parser.add_argument("-v", "--verbose", action="store_true", help="도구 호출과 결과를 단계별로 출력")
    args = parser.parse_args()

    try:
        agent = create_agent()
    except AgentConfigError as exc:
        print(f"설정 오류: {exc}")
        return 1

    def ask(question: str) -> None:
        try:
            state = agent.ask(question, print_step if args.verbose else None)
        except Exception as exc:  # API 키 오류, 모델명 오류, 네트워크 오류 등을 원인과 함께 보여 준다
            print(f"실행 오류: {type(exc).__name__}: {exc}")
            return
        print(state["answer"])

    if args.question:
        ask(args.question)
        return 0

    while True:
        question = input("\n질문> ").strip()
        if not question:
            return 0
        ask(question)


if __name__ == "__main__":
    sys.exit(main())
