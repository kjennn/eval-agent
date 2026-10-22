"""MCP 서버 테스트.

- 인메모리 Client: 서버 객체를 같은 프로세스 안에서 직접 연결한다. (빠르고 DB는 메모리 SQLite)
- stdio Client: 실제로 `python -m eval_agent.mcp_server` 프로세스를 띄워 표준 입출력으로 통신한다.
  Claude Desktop/Code가 하는 것과 같은 방식이라 '진짜 연결'을 검증한다.

MCP Client는 비동기(async)라서 테스트에서는 asyncio.run()으로 감싼다. (pytest 플러그인 없이 쓰려는 선택)
"""

import asyncio
import json
import sys

import pytest
from mcp import Client, StdioServerParameters
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from eval_agent.agent.langchain_tools import build_tools
from eval_agent.mcp_server import create_server
from eval_agent.models import Base
from eval_agent.seed_data import build_dataset, insert_dataset
from eval_agent.tools import compare_years, get_grade_distribution, get_org_summary
from eval_agent.tools.descriptions import TOOL_DESCRIPTIONS


@pytest.fixture(scope="module")
def server(session_factory):
    return create_server(session_factory)


def call(server, name: str, args: dict):
    async def go():
        async with Client(server) as client:
            return await client.call_tool(name, args)

    return asyncio.run(go())


def list_tools(server):
    async def go():
        async with Client(server) as client:
            return (await client.list_tools()).tools

    return asyncio.run(go())


def test_도구_4개가_이름과_필수_파라미터와_함께_노출된다(server):
    tools = {t.name: t for t in list_tools(server)}
    assert set(tools) == {"get_grade_distribution", "compare_years", "get_org_summary", "search_policy_docs"}
    assert tools["get_grade_distribution"].input_schema["required"] == ["year"]  # org_name, eval_type은 선택
    assert tools["compare_years"].input_schema["required"] == ["org_name", "year_from", "year_to"]
    assert tools["get_org_summary"].input_schema["required"] == ["year", "org_name"]
    assert tools["search_policy_docs"].input_schema["required"] == ["query"]


def test_도구_설명은_에이전트와_MCP가_같은_문구를_쓴다(server, session_factory):
    mcp_desc = {t.name: t.description for t in list_tools(server)}
    agent_desc = {t.name: t.description for t in build_tools(session_factory)}
    assert mcp_desc == agent_desc == TOOL_DESCRIPTIONS


def test_도구_파라미터_이름은_에이전트와_MCP가_같다(server, session_factory):
    mcp_params = {t.name: set(t.input_schema["properties"]) for t in list_tools(server)}
    agent_params = {t.name: set(t.args) for t in build_tools(session_factory)}
    assert mcp_params == agent_params


def test_호출_결과는_도구_함수의_결과와_같다(server, db):
    r = call(server, "get_grade_distribution", {"year": 2025, "org_name": "영업본부", "eval_type": "성과"})
    assert r.is_error is False
    assert r.structured_content == get_grade_distribution(db, 2025, "영업본부", "성과")
    # 텍스트 콘텐츠로도 같은 JSON이 간다 (구조화 결과를 못 읽는 클라이언트를 위해)
    assert json.loads(r.content[0].text) == r.structured_content

    assert call(server, "compare_years", {"org_name": "영업본부", "year_from": 2024, "year_to": 2025}).structured_content == compare_years(db, "영업본부", 2024, 2025)
    assert call(server, "get_org_summary", {"year": 2025, "org_name": "개발본부"}).structured_content == get_org_summary(db, 2025, "개발본부")


def test_데이터_없음은_오류가_아니라_안내_결과로_온다(server):
    r = call(server, "get_grade_distribution", {"year": 2023})
    assert r.is_error is False  # 에이전트와 같은 방식: LLM이 읽고 스스로 복구할 수 있는 정상 결과
    assert r.structured_content["error"] == "no_data"
    assert r.structured_content["available_years"] == [2024, 2025]


@pytest.mark.parametrize("args", [{"org_name": "영업본부"}, {"year": "abc"}])  # year 누락 / 타입 오류
def test_잘못된_인자는_MCP_오류로_거절된다(server, args):
    r = call(server, "get_grade_distribution", args)
    assert r.is_error is True


def test_기준_문서_검색도_호출된다(server):
    r = call(server, "search_policy_docs", {"query": "영업본부 B등급 허용 상한"})
    assert r.structured_content["found"] is True
    assert r.structured_content["results"][0]["source"] == "02-org-exceptions.md"


def test_결과에_개인_이름이_새지_않는다(server):
    results = [
        call(server, "get_grade_distribution", {"year": 2025}).structured_content,
        call(server, "get_org_summary", {"year": 2025, "org_name": "개발본부"}).structured_content,
    ]
    dumped = "".join(json.dumps(r, ensure_ascii=False) for r in results)
    assert not any(e.name in dumped for e in build_dataset().employees)


def test_서버_지침에_더미_데이터와_읽기전용이_명시되어_있다(server):
    async def go():
        async with Client(server) as client:
            return client.instructions

    instructions = asyncio.run(go())
    assert "더미 데이터" in instructions and "읽기 전용" in instructions


def test_실제_stdio_프로세스로_연결해서_도구를_호출한다(tmp_path):
    # 파일 SQLite에 시드를 넣고, 서버 프로세스가 DATABASE_URL로 그 DB를 보게 한다.
    url = f"sqlite:///{tmp_path / 'eval.db'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        insert_dataset(s, build_dataset())
        s.commit()
    engine.dispose()

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "eval_agent.mcp_server"],
        env={"DATABASE_URL": url},
    )

    async def go():
        async with Client(params) as client:
            tools = await client.list_tools()
            result = await client.call_tool(
                "get_org_summary", {"year": 2025, "org_name": "개발본부"}
            )
            return [t.name for t in tools.tools], result

    names, result = asyncio.run(go())
    assert len(names) == 4
    assert result.is_error is False
    assert result.structured_content["headcount"] == 80
    assert result.structured_content["avg_score_by_eval_type"]["다면"] > 0
