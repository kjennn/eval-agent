# 단계별 구현 기록

프로젝트를 1~6단계로 나눠 만든 기록입니다. 각 단계의 실행 방법, 그때 정한 것, 테스트, 한계를 적었습니다. 처음 실행해 보려는 경우에는 [README의 빠른 시작](../README.md#빠른-시작)을 먼저 보세요.

| 단계 | 내용 |
|------|------|
| 1 | 프로젝트 구조, uv 환경, docker-compose(PostgreSQL) |
| 2 | 스키마, 더미 데이터 시드 스크립트 |
| 3 | 도구 4개, pytest |
| 4 | LangGraph 에이전트, CLI |
| 5 | FastAPI `POST /ask` |
| 6 | MCP 서버 (Claude Desktop/Code에서 도구 사용) |

## 1단계: 환경 준비

내 PC에서 DB와 Python 환경이 제대로 갖춰졌는지 확인하는 절차입니다.

```bash
cp .env.example .env                       # 설정 파일 생성 (.env는 커밋되지 않음)
docker compose up -d                       # PostgreSQL 컨테이너 기동
uv sync                                    # Python 3.12 가상환경 + 의존성 설치
uv run python scripts/check_db.py          # DB 접속 확인
uv run pytest                              # 테스트 실행
```

| 명령 | 하는 일 |
|------|---------|
| `cp .env.example .env` | 견본으로 실제 설정 파일을 만듭니다. DB 접속 정보와 API 키 같은 비밀값을 여기에 둡니다. |
| `docker compose up -d` | PostgreSQL 16 컨테이너를 백그라운드로 띄웁니다. 데이터는 Docker 볼륨에 남아서 껐다 켜도 유지됩니다. |
| `uv sync` | `pyproject.toml`과 `uv.lock`대로 `.venv`를 만들고 라이브러리를 설치합니다. Python 3.12가 없으면 uv가 받아 옵니다. |
| `uv run python scripts/check_db.py` | `.env`의 `DATABASE_URL`로 접속해 `SELECT version()`을 실행합니다. `DB 연결 성공: PostgreSQL 16...`이 나오면 정상입니다. |
| `uv run pytest` | `tests/` 아래 테스트를 모두 실행합니다. |

`Cannot connect to the Docker daemon` 오류가 나면 Docker Desktop이 꺼져 있는 것입니다.

## 2단계: 스키마와 더미 데이터

```bash
uv run python scripts/seed.py            # 테이블 생성 + 더미 데이터 입력 (이미 있으면 중단)
uv run python scripts/seed.py --reset    # 전체 삭제 후 재생성 ('yes' 입력 필요)
```

- 데이터는 모두 가짜이고, 같은 seed로 항상 같은 결과가 나옵니다.
- 영업본부는 2025년 B등급 비율이 약 68%가 되게 일부러 높게 만들었습니다. (기준 문서의 영업본부 B등급 상한은 65%)
- 테이블이 없다는 오류(`relation ... does not exist`)가 나면 시드를 아직 안 돌린 것입니다.

## 3단계: 도구 4개

모든 도구는 정해진 파라미터만 받는 읽기 전용 함수이고, 개인 이름 없이 집계만 돌려줍니다. 

조회가 안 되면 예외 대신 `{"error": ...}`를 돌려줘서 LLM이 "데이터가 없다"고 답할 수 있게 했습니다.

| 도구 | 파라미터 | 결과 |
|------|----------|------|
| `get_grade_distribution` | year, org_name?, eval_type? | 등급별 인원과 비율, 하위 조직별 breakdown |
| `compare_years` | org_name, year_from, year_to | 두 연도 분포와 등급별 변화(%p) |
| `get_org_summary` | year, org_name | 인원수, 평균 점수, 평가유형별 평균 |
| `search_policy_docs` | query, top_k? | 기준 문서에서 관련 문단 (키워드 검색) |

```bash
uv run pytest        # DB 없이 메모리 SQLite로 도구를 검증한다
```

## 4단계: LangGraph 에이전트와 CLI

LLM이 3단계 도구 중 필요한 것을 골라 호출하고, 결과를 보고 다시 판단해서 최종 답변을 만듭니다.

### 준비

`.env`에 발급받은 API 키와 모델명을 넣습니다. `.env`는 커밋되지 않습니다. 키를 코드나 `.env.example`에 넣지 않습니다.

```
ANTHROPIC_API_KEY=발급받은_키
ANTHROPIC_MODEL=claude-haiku-5-5      # 개발 중에는 저렴한 모델로 시작
AGENT_MAX_ITERATIONS=6                # 도구 호출 반복 상한 (무한 루프, 비용 폭주 방지)
AGENT_MAX_TOKENS=2048                 # LLM 답변 한 번의 최대 길이 (너무 작으면 답변이 잘린다)
```

### 실행

```bash
uv run python scripts/ask.py "2025년 본부별 B등급 비율을 비교해줘"
uv run python scripts/ask.py -v "개발본부 다면평가 평균은?"    # -v: 도구 호출과 결과를 단계별로 출력
uv run python scripts/ask.py                                    # 질문 없이 실행하면 대화형
```

질문마다 독립적으로 실행되고 이전 질문은 기억하지 않습니다.

### 그래프 흐름

```
                 ┌──────────── 도구 호출 요청 있음 & 한도 미만 ───────────┐
                 ▼                                                        │
    START → [agent] ──┬── 도구 호출 요청 없음 ──→ [finalize] → END         │
                      ├── 도구 호출 요청 있음 & 한도 도달 → [limit] → END   │
                      └───────────────→ [tools] ───────────────────────────┘
```

- `agent`: LLM을 한 번 호출합니다. 도구 호출을 요청하거나 최종 답변을 합니다.
- `tools`: 요청된 도구를 실행하고 결과를 상태에 쌓습니다.
- `finalize`: 최종 답변 뒤에 실제 호출 기록에서 뽑은 근거를 코드로 붙입니다.
- `limit`: 반복 한도에 도달하면 "추가 확인이 필요합니다"와 함께 멈춥니다.

### 이 단계에서 정한 것

- 근거는 LLM이 아니라 코드가 붙입니다. (LLM은 조건을 틀리게 쓸 수 있습니다.)
- 반복 한도에 닿아도 예외로 죽지 않고 안내와 호출 기록을 돌려줍니다.
- `build_graph(llm, ...)`가 LLM을 인자로 받습니다. 테스트에서는 정해진 응답을 내는 가짜 LLM을 넣습니다.
- 조회 가능한 연도를 프롬프트에 DB 값으로 넣습니다. "작년", "올해" 같은 표현을 코드에 박힌 연도 없이 해석하게 하려는 것입니다.
- `AGENT_MAX_TOKENS`로 답변 길이(비용) 상한을 둡니다. 처음 1024로 했더니 답변이 문장 중간에 잘려서 2048로 올리고, 프롬프트에서 간결하게 쓰게 하고, 그래도 잘리면 `stop_reason`을 보고 "잘렸습니다" 안내를 붙입니다.
- `temperature`는 보내지 않습니다. 일부 최신 모델이 거절해서(400 오류) 뺐습니다. 그래서 같은 질문에도 표현이 달라질 수 있습니다.

### 테스트

```bash
uv run pytest        # 가짜 LLM으로 그래프 흐름, 반복 한도, 근거 첨부를 검증한다 (API 호출 없음, 비용 없음)
```

가짜 LLM으로는 그래프 배선만 검증됩니다. 실제 Claude가 도구를 알맞게 고르는지, 답변 규칙을 지키는지는 CLI로 테스트 질문을 직접 던져서 확인했습니다.

## 5단계: FastAPI `POST /ask`

에이전트를 HTTP API로 감쌌습니다. 서버가 시작될 때 에이전트(LLM 클라이언트, DB 연결 풀, 컴파일된 그래프)를 한 번만 만들고 요청마다 재사용합니다.

### 실행

```bash
uv run uvicorn eval_agent.api.app:app --host 127.0.0.1 --port 8000
```

- API 문서(Swagger UI): http://127.0.0.1:8000/docs
- 이 API는 호출할 때마다 Claude API 비용이 듭니다. 인증이 없으므로 외부에 공개하지 않습니다. 기본 설정(127.0.0.1)은 내 PC에서만 접속됩니다.
- `http://127.0.0.1:8000/` 루트 주소는 아무것도 없어서 빈 화면(404)이 나옵니다. `/docs`로 들어가면 됩니다.

### 호출 예시

```bash
curl -s -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "개발본부 다면평가 평균은?"}'
```

응답 예시:

```json
{
  "answer": "개발본부 2025년 다면평가 평균은 76.66점입니다. ...\n\n근거(호출한 도구와 조건):\n- get_org_summary(year=2025, org_name='개발본부')",
  "tool_calls": [
    {"name": "get_org_summary", "args": {"year": 2025, "org_name": "개발본부"}, "error": null}
  ],
  "iterations": 2
}
```

| 엔드포인트 | 설명 |
|------------|------|
| `POST /ask` | 질문(1~500자)을 받아 답변, 도구 호출 목록, LLM 호출 횟수를 돌려줍니다. |
| `GET /health` | 서버 상태 확인 |

| 상태 코드 | 의미 |
|-----------|------|
| 200 | 정상 |
| 422 | 입력 오류 (질문 없음, 공백뿐, 500자 초과). LLM을 호출하지 않습니다. |
| 502 | LLM 호출 실패. 원인(API 키 오류 등)은 서버 로그에만 남기고 응답에는 노출하지 않습니다. |

### 이 단계에서 정한 것

- 에이전트는 서버 시작 때 한 번 만듭니다. 요청마다 만들면 DB 연결 풀과 LLM 클라이언트를 매번 새로 만들게 됩니다. 설정이 잘못됐으면(API 키 없음 등) 요청이 들어온 뒤가 아니라 서버 시작 때 바로 실패합니다.
- 엔드포인트는 `async def`가 아니라 `def`로 만듭니다. 에이전트가 블로킹 코드라서 `async def` 안에서 부르면 이벤트 루프가 막혀 서버 전체가 그동안 멈춥니다. `def`면 FastAPI가 스레드 풀에서 실행해 줍니다.
- 질문 길이를 500자로 제한합니다. 호출마다 비용이 드는 API라서 큰 입력을 앞에서 막습니다.
- 오류 원인은 응답에 노출하지 않습니다. 내부 예외 메시지에 API 키 오류나 내부 구조가 담길 수 있어서 로그에만 남깁니다.
- `create_app(agent=...)`로 에이전트를 주입할 수 있습니다. 테스트에서는 가짜 에이전트를 꽂습니다.

### 테스트

```bash
uv run pytest        # TestClient로 입력 검증, 오류 처리, HTTP부터 도구 실행까지의 흐름을 검증한다
```

### 한계

- 인증과 호출 횟수 제한(rate limit)이 없습니다.
- 질문마다 독립 실행이고 대화 기억이 없습니다.
- LLM 응답을 기다리는 동안 스레드가 점유돼서, 동시 요청이 많아지면 스레드 풀 크기가 한계가 됩니다.

## 6단계: MCP 서버

3단계의 도구 4개를 MCP(Model Context Protocol) 서버로 노출했습니다. Claude Desktop이나 Claude Code가 에이전트(4~5단계) 없이 이 도구를 직접 쓸 수 있습니다.

### 에이전트와 MCP 서버의 차이

| | 에이전트 (4~5단계) | MCP 서버 (6단계) |
|---|---|---|
| LLM이 있는 곳 | 내 서버 (내가 Claude API를 호출) | Claude Desktop/Code 쪽 |
| 내 코드가 하는 일 | 질문 → 최종 답변 | 도구 목록 제공, 도구 실행 |
| Claude API 키와 비용 | 필요 | 필요 없음 |
| 반복 한도, 답변 규칙 | 내가 관리 | 클라이언트(Claude)가 관리 |

### 실행과 연결

Claude Desktop/Code 연결 방법은 [MCP 서버 연결 가이드](mcp-setup.md)에 따로 정리했습니다.

### 이 단계에서 정한 것

- 3단계 함수는 건드리지 않고 `mcp_server/server.py`에 얇은 어댑터만 더했습니다. 세션을 열어 함수를 호출하고 결과 dict를 돌려줍니다.
- 도구 설명은 에이전트와 MCP가 같은 파일(`tools/descriptions.py`)을 씁니다. 테스트가 같은지 확인합니다.
- 데이터가 없으면 에이전트와 같은 방식으로 안내 결과를 돌려줍니다. 필수 인자 누락이나 타입 오류는 MCP의 오류 응답(`is_error`)으로 거절됩니다.
- stdout은 프로토콜 전용입니다. 서버 코드에서 `print()`를 쓰면 메시지가 깨져서 연결이 끊깁니다. 실제 프로세스를 띄워서 통신하는 테스트가 이를 지킵니다.
- mcp 2.x에서는 `FastMCP`가 `MCPServer`로 이름이 바뀌었습니다. 이 프로젝트는 2.x(`from mcp.server.mcpserver import MCPServer`)를 씁니다.

### 테스트

```bash
uv run pytest        # 인메모리 클라이언트와 실제 stdio 프로세스로 도구 목록, 호출 결과, 오류 처리를 검증한다
```

### 한계

- 서버가 DB에 쓰는 계정을 따로 제한하지 않았습니다. 도구가 읽기 전용 함수라서 안전하지만, 운영이라면 DB 계정 자체를 읽기 전용으로 분리해야 합니다.
- 인증이 없습니다. stdio라서 로컬 프로세스 간 통신에 한정되고, 원격(HTTP)으로 공개하려면 인증이 필요합니다.
- 더미 데이터이고 실제 고객사 데이터는 연결하지 않았습니다.

[README로 돌아가기](../README.md)
