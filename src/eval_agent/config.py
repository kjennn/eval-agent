"""환경변수 기반 설정.

Spring의 application.yml + @ConfigurationProperties에 해당하는 역할이다.
다른 점: Python에는 프레임워크가 주는 설정 주입이 없어서,
.env를 읽어 os.environ에 올리고(load_dotenv) 직접 꺼내 쓴다.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# 프로젝트 루트의 .env를 읽어 환경변수로 올린다. 이미 설정된 환경변수는 덮어쓰지 않는다.
load_dotenv()


@dataclass(frozen=True)  # frozen=True: 생성 후 값 변경 불가 (Java의 record / 불변 객체와 비슷)
class Settings:
    database_url: str
    anthropic_api_key: str
    anthropic_model: str
    agent_max_iterations: int


def get_settings() -> Settings:
    """호출 시점의 환경변수로 Settings를 만든다.

    `-> Settings`는 타입힌트다. 실행에는 영향이 없고, IDE와 mypy 같은 도구가 읽는다.
    """
    return Settings(
        database_url=os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://eval:eval_dev_password@localhost:5432/eval_agent",
        ),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", ""),
        agent_max_iterations=int(os.environ.get("AGENT_MAX_ITERATIONS", "6")),
    )
