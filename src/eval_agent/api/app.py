"""FastAPI 서버: POST /ask.

Spring MVC와 비교
- `@app.post("/ask")` ≈ `@PostMapping("/ask")`.  `Depends(...)` ≈ 의존성 주입(@Autowired).
- Pydantic 모델(AskRequest/AskResponse)이 요청·응답 DTO이면서 검증(@Valid)까지 맡는다.
  검증에 실패하면 FastAPI가 알아서 422 응답을 만든다. 직접 코드를 쓸 필요가 없다.
- `/docs`에서 자동 생성된 API 문서(Swagger UI)를 볼 수 있다. (springdoc-openapi와 같은 역할)
- lifespan: 서버가 시작될 때 한 번 실행되고(@PostConstruct) 종료될 때 정리하는(@PreDestroy) 구간이다.
  에이전트(LLM 클라이언트, DB 연결 풀, 컴파일된 그래프)는 만드는 비용이 있어서 여기서 한 번만 만든다.

동기 vs 비동기 (새 개념)
- 엔드포인트를 `def`로 만들면 FastAPI가 스레드 풀에서 실행한다. (Spring MVC의 요청당 스레드와 비슷)
- `async def`로 만들면 이벤트 루프 위에서 실행된다. 이때 안에서 '블로킹 호출'(우리 에이전트의 LLM·DB 호출)을
  하면 서버 전체가 그동안 멈춘다. 에이전트는 동기 코드이므로 `def`를 쓴다.
"""

import logging
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, StringConstraints

from eval_agent.agent.factory import EvalAgent, create_agent
from eval_agent.agent.graph import collect_tool_calls

logger = logging.getLogger(__name__)

# 앞뒤 공백을 자르고 1~500자만 허용한다. 호출마다 비용이 드는 API라서 입력 길이에도 상한을 둔다.
Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class AskRequest(BaseModel):
    question: Question


class ToolCallInfo(BaseModel):
    name: str
    args: dict[str, Any]
    error: str | None = None  # 도구 결과가 에러였을 때의 코드 (예: no_data)


class AskResponse(BaseModel):
    answer: str  # 근거(호출한 도구와 조건)까지 포함된 최종 답변
    tool_calls: list[ToolCallInfo]  # 같은 근거를 구조화한 목록 (화면이나 로그에서 쓰기 쉽게)
    iterations: int  # LLM을 몇 번 호출했는가


def get_agent(request: Request) -> EvalAgent:
    return request.app.state.agent


def create_app(agent: EvalAgent | None = None) -> FastAPI:
    """agent를 넘기면 그것을 쓰고(테스트용), 없으면 서버 시작 때 설정(.env)으로 만든다."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 설정이 잘못됐으면(API 키 없음 등) 여기서 예외가 나서 서버가 시작되지 않는다.
        # 요청이 들어온 뒤에야 실패하는 것보다 시작할 때 바로 알리는 편이 낫다.
        app.state.agent = agent if agent is not None else create_agent()
        yield

    app = FastAPI(title="eval-agent", description="평가 결과 분석 에이전트", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/ask", response_model=AskResponse)
    def ask(body: AskRequest, agent: Annotated[EvalAgent, Depends(get_agent)]) -> AskResponse:
        try:
            state = agent.ask(body.question)
        except Exception:
            # 상세 원인(API 키 오류, 네트워크 오류 등)은 서버 로그에만 남기고, 클라이언트에는 일반 메시지만 준다.
            logger.exception("에이전트 실행 실패")
            raise HTTPException(
                status_code=502, detail="LLM 호출 중 오류가 발생했습니다. 서버 로그를 확인하세요."
            )
        return AskResponse(
            answer=state["answer"],
            tool_calls=[ToolCallInfo(**c) for c in collect_tool_calls(state["messages"])],
            iterations=state["iterations"],
        )

    return app


# uvicorn이 가져다 쓰는 앱 객체: uvicorn eval_agent.api.app:app
# 가져오는 시점에는 에이전트를 만들지 않는다. (lifespan은 서버가 시작될 때만 실행된다)
app = create_app()
