# Python이 처음이라면: 프로젝트 읽는 법

Java/Spring 개발자 기준으로, 이 프로젝트의 파일이 무엇에 해당하는지 정리했습니다.

## 도구와 설정 파일

| Python 쪽 | Java/Spring에서 대응되는 것 | 설명 |
|-----------|----------------------------|------|
| `pyproject.toml` | `pom.xml` / `build.gradle` | 프로젝트 이름, 의존성, 테스트 설정이 들어 있습니다. |
| `uv` | Maven/Gradle | 의존성 설치와 실행을 해 주는 도구. `uv sync`가 `mvn install` 같은 역할입니다. |
| `uv.lock` | 의존성 버전 잠금 파일 | 모든 PC에서 같은 버전이 깔리게 합니다. |
| `.venv/` | (프로젝트별로 격리된 JDK + 라이브러리) | 이 프로젝트 전용 Python 환경. 다른 프로젝트와 라이브러리가 섞이지 않습니다. 커밋하지 않습니다. |
| `.python-version` | JDK 버전 지정 | 3.12를 씁니다. |
| `.env` | `application.yml`의 환경변수 | DB 접속 정보, API 키 같은 비밀값. 커밋하지 않습니다. `.env.example`은 견본입니다. |
| `docker-compose.yml` | 그대로 | PostgreSQL 컨테이너를 띄웁니다. |

## 코드 폴더

| 위치 | Java 쪽 대응 | 하는 일 |
|------|-------------|---------|
| `src/eval_agent/` | `src/main/java/.../` | 실제 코드. 폴더 하나가 패키지 하나입니다. |
| `__init__.py` | 패키지 표시 | 이 파일이 있는 폴더를 패키지로 인식합니다. 안에서 "외부에 공개할 것"만 골라 내보내는 용도로도 씁니다. |
| `models.py` | `@Entity` 클래스들 | SQLAlchemy로 테이블을 클래스로 정의합니다. JPA와 같은 역할입니다. |
| `tools/` | Service | 도구 4개. DB를 조회해서 결과 dict를 돌려주는 함수들입니다. 클래스가 아니라 함수로 만들었습니다. |
| `agent/` | (에이전트 로직) | LangGraph로 "LLM 호출 → 도구 실행 → 다시 LLM 호출" 흐름을 만듭니다. |
| `api/` | Controller | FastAPI. Spring MVC의 `@RestController`와 비슷합니다. |
| `mcp_server/` | Controller (다른 프로토콜) | 같은 도구를 MCP 형식으로 노출합니다. |
| `config.py` | `@ConfigurationProperties` | `.env`에서 설정을 읽어 한 곳에 모읍니다. |
| `scripts/` | main 클래스들 | 시드, CLI처럼 직접 실행하는 파일. |
| `tests/` | `src/test/java` | pytest 테스트. `conftest.py`는 테스트 공통 준비(DB 등)를 두는 파일입니다. |
| `docs/policy/` | (검색 대상 문서) | 기준 문서 4개. `search_policy_docs`가 여기서 찾습니다. |

## 질문 하나가 처리되는 흐름

"개발본부 다면평가 평균은?"을 `POST /ask`로 보냈을 때입니다.

1. `api/app.py`가 요청을 받아 길이 등을 검증하고 에이전트를 호출합니다. (422는 여기서 반환합니다.)
2. `agent/graph.py`의 그래프가 시작됩니다. `agent` 노드에서 Claude를 호출하면 Claude가 "`get_org_summary`를 `year=2025, org_name=개발본부`로 불러라"라고 요청합니다.
3. `tools` 노드가 `agent/langchain_tools.py`를 거쳐 `tools/evaluation.py`의 `get_org_summary()`를 실행합니다. 이 함수가 PostgreSQL을 조회합니다.
4. 결과(JSON)를 Claude에게 돌려주면 Claude가 답변을 만듭니다. 도구 요청이 더 없으면 `finalize` 노드로 갑니다.
5. `finalize`가 답변 끝에 "근거: get_org_summary(year=2025, org_name='개발본부')"를 코드로 붙여서 응답합니다.

MCP로 쓸 때는 2~4번을 Claude Desktop이 대신합니다. Claude Desktop이 `mcp_server/server.py`에 도구를 요청하고, 서버가 같은 `tools/` 함수를 실행해 결과를 돌려줍니다.

## 코드를 읽는 순서

1. `models.py`: 테이블 구조
2. `tools/evaluation.py`: 도구가 DB를 어떻게 조회하는지 (여기까지는 Spring 서비스 코드와 비슷합니다)
3. `tests/test_tools_evaluation.py`: 도구를 어떻게 검증하는지
4. `agent/graph.py`: LangGraph 흐름 (이 프로젝트에서 새로 배우는 부분)
5. `api/app.py`, `mcp_server/server.py`: 도구를 바깥에 노출하는 방법

---

[README로 돌아가기](../README.md)
