# 임베딩 검색을 정말 썼는지 확인하는 법

에이전트의 답만 보면 기준 문서를 키워드로 찾았는지, 임베딩 모델과 벡터DB(pgvector)로 찾았는지 구분이 안 됩니다. 이 문서는 **검색 한 번을 끝까지 따라가며 증거를 확인하는 방법**을 정리합니다. 구현 과정은 [임베딩 검색 작업 기록](embedding-search.md)에 있습니다.

## 한 번에 확인하기: `trace_search.py`

```bash
uv run python scripts/trace_search.py                                # 기본 질문: "평가 결과가 억울하면 어떻게 해?"
uv run python scripts/trace_search.py "평가 결과에 이의를 제기하려면?"   # 원하는 질문
```

- 필요한 것: Docker DB 실행, `.env`의 `VOYAGE_API_KEY`와 `EMBEDDING_MODEL`, 색인(`scripts/index_policy.py`)
- Voyage API를 한 번 부릅니다(무료 토큰 안). Claude API는 부르지 않습니다.

아래는 2026-11-20에 실제로 실행한 출력입니다.

```
=== 1. DB에 저장된 문단 벡터 (policy_chunk, 앞 3개)
  개요 | voyage-4 | 1024차원 | [-0.0015420386,-0.033706177,0.031124478,-0.0466896...
  1. 적용 범위 | voyage-4 | 1024차원 | [0.013524503,-0.013767931,0.03094512,-0.0056072585...
  2. 권장 배분 비율 | voyage-4 | 1024차원 | [0.034408484,-0.012199981,0.031854235,0.009299329,...

=== 2. 검색 과정 (일어난 순서대로)
  [SQL] BEGIN (implicit)
  [SQL] SELECT count(*) AS count_1 FROM policy_chunk WHERE policy_chunk.embedding_model = %(embedding_model_1)s::VARCHAR
  [SQL] [generated in 0.00009s] {'embedding_model_1': 'voyage-4'}
  [Voyage] model=voyage-4, 입력=['평가 결과가 억울하면 어떻게 해?']
  [Voyage] 받은 벡터: 1024차원, 앞 3개 값=[0.0469, -0.0156, -0.0291]
  [SQL] SELECT policy_chunk.id, policy_chunk.source, policy_chunk.document, policy_chunk.section, policy_chunk.text, policy_chunk.embedding_model, policy_chunk.embedding, policy_chunk.embedding <=> %(embedding_1)s AS distance FROM policy_chunk WHERE policy_chunk.embedding_model = %(embedding_model_1)s::VARCHAR ORDER BY distance LIMIT %(param_1)s::INTEGER
  [SQL] [generated in 0.00141s] {'embedding_1': '[0.046875081956386566,-0.015622350387275219,-0.02906673401594162, ... (총 1024개 중 앞 3개)]', 'embedding_model_1': 'voyage-4', 'param_1': 3}
  [SQL] ROLLBACK

=== 3. 도구 결과
  method = vector
  0.492  04-calibration-and-appeal.md / 3. 이의신청
  0.444  04-calibration-and-appeal.md / 1. 평가 보정 회의
  0.433  04-calibration-and-appeal.md / 2. 보정 시 확인 항목
```

Voyage가 돌려주는 벡터의 끝자리 값은 실행할 때마다 조금씩 다를 수 있습니다. 점수도 소수 셋째 자리에서 0.001 정도 차이가 납니다.

## 출력 읽는 법: 증거 4가지

### ① 문서는 미리 벡터로 저장돼 있다 (pgvector)

`policy_chunk` 테이블에 문단마다 **숫자 1024개짜리 벡터**가 들어 있습니다. `index_policy.py`가 `voyage-4`로 만들어 넣은 값입니다. `embedding_model` 컬럼에 어떤 모델로 만든 벡터인지 기록돼 있습니다.

### ② 질문을 임베딩 모델로 보낸다 (Voyage)

`[Voyage]` 줄이 질문 문장을 Voyage API에 보내고, 숫자 1024개짜리 벡터를 받은 기록입니다. 키워드 검색이었다면 이 호출 자체가 없습니다.

그 바로 앞의 `count(*)` 쿼리는 **현재 모델로 만든 색인이 있는지** 먼저 확인하는 쿼리입니다. 색인이 없으면 Voyage를 부르지 않고 키워드 검색으로 넘어갑니다.

### ③ 벡터끼리 거리를 재서 찾는다 (벡터 검색)

```sql
policy_chunk.embedding <=> %(embedding_1)s AS distance
...
ORDER BY distance LIMIT 3
```

`<=>`가 핵심입니다. pgvector가 제공하는 **코사인 거리 연산자**이고, 일반 PostgreSQL에는 없습니다. `embedding_1`에는 ②에서 받은 질문 벡터가 들어가고, DB가 문단 벡터 20개와의 거리를 재서 가까운 순서로 3개를 돌려줍니다.

| 검색 방식 | 비교하는 것 | 어디서 계산하나 |
|-----------|-------------|----------------|
| 임베딩 검색 | 벡터 사이의 거리 (`<=>`) | PostgreSQL (pgvector) |
| 키워드 검색 | 질문 단어가 문단에 들어 있는 횟수 | 파이썬 (DB를 쓰지 않음) |

### ④ 결과가 그것을 말해 준다

- `method = vector`: 임베딩 검색으로 찾았다는 표시입니다.
- 점수가 0~1 사이 소수입니다. 코사인 유사도(1 - 거리)입니다.
- 질문에 "이의신청"이라는 글자가 없는데 **이의신청 절이 1위**입니다. 키워드 검색은 같은 질문에서 "평가 보정 회의"를 1위로 올리고 이의신청 절은 3위 안에도 넣지 못했습니다. 의미로 찾았다는 증거입니다.

## 에이전트나 MCP로 테스트할 때 구분하는 법

### `method` 필드 보기 (가장 확실)

CLI에서 `-v`로 실행하면 `search_policy_docs`의 결과 JSON이 보입니다.

```bash
uv run python scripts/ask.py -v "평가 결과가 억울하면 어떻게 해?"
```

| `method` | 뜻 |
|----------|----|
| `"vector"` | 임베딩 모델 + pgvector로 찾았다 |
| `"keyword"` + `fallback_reason` 있음 | 임베딩을 쓰려 했지만 못 써서 키워드로 대체했다 (이유가 적혀 있다) |
| `"keyword"` + `fallback_reason` 없음 | 처음부터 키워드 검색 (`VOYAGE_API_KEY`가 없음) |

Claude Desktop(MCP)에서는 도구 호출 블록을 펼치면 같은 결과 JSON을 볼 수 있습니다.

### 점수 모양 보기

| | 임베딩 검색 | 키워드 검색 |
|---|---|---|
| `score` 예시 | 0.492 | 204 |
| 의미 | 코사인 유사도 (0~1) | 일치한 키워드 수 × 100 + 등장 횟수 |

### 글자가 겹치지 않는 질문으로 시험하기

"억울하면 어떻게 해?"(→ 이의신청), "영업본부가 B를 많이 줘도 돼?"(→ 영업본부 예외 규정)처럼 문서와 단어가 겹치지 않는 질문에서 정답이 나오면 키워드 방식으로는 설명이 안 됩니다. 두 방식을 나란히 보려면:

```bash
uv run python scripts/compare_search.py "평가 결과가 억울하면 어떻게 해?"
```

### Voyage 대시보드에서 사용량 보기

[dashboard.voyageai.com](https://dashboard.voyageai.com)의 사용량 화면에서 검색할 때마다 요청 수와 토큰이 늘어나는지 확인할 수 있습니다.

### 꺼서 비교하기

`.env`의 `VOYAGE_API_KEY` 줄 앞에 `#`을 붙이고 같은 질문을 하면 `method`가 `keyword`로 바뀌고 결과도 달라집니다. 확인한 뒤에는 `#`을 다시 지웁니다. Claude Desktop(MCP)은 `.env`를 바꾼 뒤 Cmd+Q로 재시작해야 반영됩니다.

## `method`가 `keyword`로 나올 때

| `fallback_reason` | 원인 | 해결 |
|-------------------|------|------|
| `'voyage-4' 모델로 만든 색인이 없습니다` | 색인을 안 만들었거나, `EMBEDDING_MODEL`을 바꾼 뒤 다시 안 만듦 | `uv run python scripts/index_policy.py` |
| `임베딩 검색 중 오류가 나서 키워드 검색으로 대체했습니다` | Voyage 요청 제한(결제 수단 미등록 시 분당 3회), 네트워크 오류, DB에 pgvector 없음 등 | 1분 뒤 다시 시도. 계속되면 서버 로그(stderr)에서 상세 원인 확인 |

## 이 확인 과정에서 발견한 것

③의 SQL을 보면 결과 3개를 가져오면서 `policy_chunk.embedding`, 즉 **문단 벡터(숫자 1024개)도 같이 가져옵니다.** 결과에는 쓰지 않는 값이라 불필요한 데이터 전송입니다. 문단이 20개라 지금은 체감되지 않지만, 필요한 컬럼만 고르도록 고칠 대상입니다.

[README로 돌아가기](../README.md)
