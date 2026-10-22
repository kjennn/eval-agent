"""DB 스키마 (SQLAlchemy 2.0 ORM 모델).

Java 비교:
- 클래스 하나 = JPA의 @Entity 하나. `__tablename__`이 @Table(name=...)에 해당한다.
- `Mapped[int]`는 "이 컬럼은 int"라는 타입힌트이면서 동시에 매핑 정보다.
  `int | None`은 NULL 허용(Java의 @Nullable)이라는 뜻이다.
- `mapped_column(...)`은 @Column/@Id/@JoinColumn의 옵션을 한곳에 모은 것이다.
- 다른 점: 이 프로젝트는 Flyway/Liquibase 같은 마이그레이션 도구 없이
  `Base.metadata.create_all()`로 테이블을 만든다. (한계로 README에 적을 예정)
"""

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EVAL_TYPES = ("역량", "성과", "다면")
GRADES = ("S", "A", "B", "C", "D")


class Base(DeclarativeBase):
    """모든 모델의 부모. Base.metadata가 전체 테이블 정의를 들고 있다."""


class OrgUnit(Base):
    """조직. 본부(parent_id 없음) > 팀(parent_id = 본부 id) 2단계."""

    __tablename__ = "org_unit"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("org_unit.id"))


class Employee(Base):
    __tablename__ = "employee"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(30))
    org_unit_id: Mapped[int] = mapped_column(ForeignKey("org_unit.id"))  # 소속 팀
    job_level: Mapped[str] = mapped_column(String(10))


class EvaluationCycle(Base):
    __tablename__ = "evaluation_cycle"

    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(unique=True)
    name: Mapped[str] = mapped_column(String(50))


class EvaluationResult(Base):
    __tablename__ = "evaluation_result"
    __table_args__ = (
        # 한 직원은 한 주기에 평가유형별로 결과가 하나만 있다
        UniqueConstraint("cycle_id", "employee_id", "eval_type"),
        # 허용값을 DB가 직접 검증한다 (Java의 enum 대신 CHECK 제약으로 단순하게)
        CheckConstraint("eval_type IN ('역량', '성과', '다면')", name="ck_eval_type"),
        CheckConstraint("grade IN ('S', 'A', 'B', 'C', 'D')", name="ck_grade"),
        Index("ix_result_cycle_grade", "cycle_id", "grade"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("evaluation_cycle.id"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("employee.id"))
    eval_type: Mapped[str] = mapped_column(String(10))
    # asdecimal=False: DB에서 꺼낼 때 Decimal이 아니라 float로 받는다 (JSON 변환이 쉬워짐)
    score: Mapped[float] = mapped_column(Numeric(5, 2, asdecimal=False))
    grade: Mapped[str] = mapped_column(String(1))
