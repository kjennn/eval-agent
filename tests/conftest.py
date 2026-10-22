"""모든 테스트가 공유하는 픽스처.

conftest.py는 pytest가 자동으로 읽는 파일이다. 여기 정의한 픽스처는 import 없이
테스트 함수의 파라미터 이름만 맞추면 주입된다. (JUnit의 @BeforeAll + 파라미터 주입을 합친 느낌)
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from eval_agent.models import Base
from eval_agent.seed_data import Dataset, build_dataset, insert_dataset


@pytest.fixture(scope="session")  # 테스트 전체에서 한 번만 만든다. 도구는 읽기 전용이라 공유해도 안전하다.
def dataset() -> Dataset:
    return build_dataset()


@pytest.fixture(scope="session")
def engine(dataset: Dataset):
    """더미 데이터가 들어 있는 메모리 SQLite. (PostgreSQL 없이 빠르게 테스트하려는 용도)

    StaticPool + check_same_thread=False: 메모리 SQLite는 연결마다 별개의 DB라서, 기본 설정이면
    LangGraph가 도구를 다른 스레드에서 실행할 때 빈 DB를 보게 된다. 하나의 연결을 모두가 공유하게 한다.
    """
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        insert_dataset(session, dataset)
        session.commit()
    return engine


@pytest.fixture(scope="session")
def session_factory(engine):
    return sessionmaker(engine)


@pytest.fixture(scope="session")
def db(session_factory):
    with session_factory() as session:
        yield session  # yield 앞은 준비, 뒤는 정리(with 블록 종료 시 세션 닫힘)
