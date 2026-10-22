"""DB 연결 확인용 스크립트: uv run python scripts/check_db.py"""

import sys

from sqlalchemy import create_engine, text

from eval_agent.config import get_settings


def main() -> int:
    engine = create_engine(get_settings().database_url)
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version()")).scalar_one()
    except Exception as exc:  # 연결 실패 원인을 그대로 보여주기 위해 넓게 잡는다
        print(f"DB 연결 실패: {exc}")
        return 1
    print(f"DB 연결 성공: {version}")
    return 0


if __name__ == "__main__":  # 이 파일을 직접 실행할 때만 main()을 호출 (Java의 public static void main 역할)
    sys.exit(main())
