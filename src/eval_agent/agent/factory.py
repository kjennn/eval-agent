"""설정에서 에이전트를 조립한다. (Spring의 @Configuration + @Bean 조립 코드에 해당)

CLI(4단계), FastAPI(5단계)가 모두 create_agent()로 같은 에이전트를 만든다.
"""

from collections.abc import Callable
from dataclasses import dataclass

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from eval_agent.agent.graph import AgentState, build_graph, run_agent
from eval_agent.agent.langchain_tools import build_tools
from eval_agent.agent.prompts import build_system_prompt
from eval_agent.config import Settings, get_settings
from eval_agent.models import EvaluationCycle


class AgentConfigError(RuntimeError):
    """에이전트를 만들 수 없는 설정 문제 (API 키나 모델명 누락)."""


@dataclass
class EvalAgent:
    graph: object
    max_iterations: int

    def ask(
        self, question: str, on_message: Callable[[BaseMessage], None] | None = None
    ) -> AgentState:
        return run_agent(self.graph, question, self.max_iterations, on_message)


def create_agent(settings: Settings | None = None) -> EvalAgent:
    settings = settings or get_settings()
    # 비용이 드는 객체를 만들기 전에 설정부터 확인한다.
    if not settings.anthropic_api_key:
        raise AgentConfigError(".env에 ANTHROPIC_API_KEY를 설정하세요.")
    if not settings.anthropic_model:
        raise AgentConfigError(".env에 ANTHROPIC_MODEL(사용할 Claude 모델명)을 설정하세요.")

    session_factory = sessionmaker(create_engine(settings.database_url))
    with session_factory() as session:
        years = list(session.scalars(select(EvaluationCycle.year).order_by(EvaluationCycle.year)))

    llm = ChatAnthropic(
        model=settings.anthropic_model,
        anthropic_api_key=settings.anthropic_api_key,
        temperature=0,  # 분석 답변은 같은 질문에 같은 답이 나오는 쪽이 낫다
        max_tokens=1024,  # 답변 길이 상한 = 비용 상한
    )
    graph = build_graph(
        llm,
        build_tools(session_factory),
        build_system_prompt(years),
        settings.agent_max_iterations,
    )
    return EvalAgent(graph, settings.agent_max_iterations)
