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

## 2단계: 스키마 + 더미 데이터

```bash
uv run python scripts/seed.py            # 테이블 생성 + 더미 데이터 입력 (이미 있으면 중단)
uv run python scripts/seed.py --reset    # 전체 삭제 후 재생성 ('yes' 입력 필요)
```

- 모든 데이터는 가짜이며, 같은 seed로 항상 같은 결과가 나온다.
- 영업본부는 2025년 B등급 비율이 약 68%로 일부러 높게 만들었다.

