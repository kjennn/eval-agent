# eval-agent

평가 결과 분석 에이전트 (Python + LangGraph + MCP). README는 7단계에서 정식으로 작성한다.

## 현재까지 (1단계)

```bash
cp .env.example .env      # 값 확인/수정
docker compose up -d      # PostgreSQL 기동
uv sync                   # 의존성 설치
uv run python scripts/check_db.py
uv run pytest
```
