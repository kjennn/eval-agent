"""스키마 생성 + 더미 데이터 입력.

    uv run python scripts/seed.py            # 테이블 생성 후 데이터 입력 (이미 데이터가 있으면 중단)
    uv run python scripts/seed.py --reset    # 모든 테이블을 삭제하고 다시 만든다 (확인 입력 필요)
"""

import argparse
import sys

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from eval_agent.config import get_settings
from eval_agent.models import Base, OrgUnit
from eval_agent.seed_data import build_dataset, insert_dataset


def main() -> int:
    parser = argparse.ArgumentParser(description="스키마 생성 + 더미 데이터 입력")
    parser.add_argument("--reset", action="store_true", help="기존 테이블을 모두 삭제하고 다시 만든다")
    args = parser.parse_args()

    engine = create_engine(get_settings().database_url)

    if args.reset:
        # 데이터를 지우는 유일한 경로. 실수로 실행하지 않도록 직접 입력을 받는다.
        answer = input("eval-agent의 모든 테이블을 삭제하고 다시 만듭니다. 계속하려면 'yes' 입력: ")
        if answer.strip() != "yes":
            print("취소했습니다.")
            return 1
        Base.metadata.drop_all(engine)

    Base.metadata.create_all(engine)  # 이미 있는 테이블은 건드리지 않는다

    with Session(engine) as session:
        if session.scalar(select(func.count()).select_from(OrgUnit)):
            print("이미 데이터가 있어서 중단합니다. 처음부터 다시 만들려면 --reset을 사용하세요.")
            return 1
        counts = insert_dataset(session, build_dataset())
        session.commit()

    for table, n in counts.items():
        print(f"{table}: {n}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
