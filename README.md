# eval-agent

평가 결과 분석 에이전트 (Python + LangGraph + MCP). README는 7단계에서 정식으로 작성한다.

## 1단계: 환경 준비

내 PC에서 DB와 파이썬 환경이 정상적으로 갖춰졌는지 확인하는 절차다.

```bash
cp .env.example .env                       # 설정 파일 생성 (.env는 커밋되지 않음)
docker compose up -d                       # PostgreSQL 컨테이너 기동
uv sync                                    # Python 3.12 가상환경 + 의존성 설치
uv run python scripts/check_db.py          # DB 접속 확인
uv run pytest                              # 테스트 실행
```

| 명령 | 하는 일 |
|------|---------|
| `cp .env.example .env` | 견본(`.env.example`)으로 실제 설정 파일을 만든다. DB 접속 정보와 API 키 같은 비밀값을 여기에 둔다. |
| `docker compose up -d` | `docker-compose.yml`대로 PostgreSQL 16 컨테이너를 백그라운드로 띄운다. 데이터는 Docker 볼륨에 저장되어 컨테이너를 껐다 켜도 남는다. |
| `uv sync` | `pyproject.toml`과 `uv.lock`대로 프로젝트 전용 가상환경(`.venv`)을 만들고 라이브러리를 설치한다. Python 3.12가 없으면 uv가 받아 온다. |
| `uv run python scripts/check_db.py` | `.env`의 `DATABASE_URL`로 DB에 접속해 `SELECT version()`을 실행한다. `DB 연결 성공: PostgreSQL 16...`이 나오면 정상이다. |
| `uv run pytest` | `tests/` 아래 테스트를 모두 실행한다. |

Docker 데몬이 꺼져 있으면 `Cannot connect to the Docker daemon` 오류가 난다. Docker Desktop을 먼저 실행한다.

## 2단계: 스키마 + 더미 데이터

```bash
uv run python scripts/seed.py            # 테이블 생성 + 더미 데이터 입력 (이미 있으면 중단)
uv run python scripts/seed.py --reset    # 전체 삭제 후 재생성 ('yes' 입력 필요)
```

- 모든 데이터는 가짜이며, 같은 seed로 항상 같은 결과가 나온다.
- 영업본부는 2025년 B등급 비율이 약 68%로 일부러 높게 만들었다.

## 3단계: 도구 4개

모든 도구는 정해진 파라미터만 받는 읽기 전용 함수이고, 개인 이름 없이 집계만 돌려준다. 조회가 안 되면 예외 대신 `{"error": ...}`를 돌려줘서 LLM이 "데이터가 없다"고 답할 수 있게 한다.

| 도구 | 파라미터 | 결과 |
|------|----------|------|
| `get_grade_distribution` | year, org_name?, eval_type? | 등급별 인원·비율, 하위 조직별 breakdown |
| `compare_years` | org_name, year_from, year_to | 두 연도 분포와 등급별 변화(%p) |
| `get_org_summary` | year, org_name | 인원수, 평균 점수, 평가유형별 평균 |
| `search_policy_docs` | query, top_k? | 기준 문서에서 관련 문단 (키워드 검색) |

```bash
uv run pytest        # DB 없이 메모리 SQLite로 도구를 검증한다
```

