# 공공데이터 하이브리드 RAG (범용)

사내 비전 데이터 + **다도메인 공공데이터**(교통안전·도로시설·대기환경·재난안전·인구·생활안전·생활복지)를
하나의 통합 구조로 적재하고, 의미(임베딩)+키워드(BM25) 하이브리드 검색과 LLM 에이전트로
**어떤 시나리오든** "찾기 → 통계/순위 → 요약·보고서"를 수행한다.

핵심: **config 기반 범용 적재** — 새 데이터셋은 코드 수정 없이 매핑 config(JSON) 한 개만 추가하면
통합 인덱스에 합류한다. 그래서 데이터셋을 늘릴수록 다룰 수 있는 질의 시나리오가 넓어진다.

> 키(API) 없이도 끝까지 동작한다. `GEMINI_API_KEY` / `DATAGO_SERVICE_KEY` / `VOYAGE_API_KEY`를
> 넣으면 Gemini 3.5 Flash + 실데이터 + Voyage 임베딩으로 승격된다.
> **설정 방법: [docs/SETUP_API_GEMINI.md](docs/SETUP_API_GEMINI.md)** / 개발 내역: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)

## 다양한 시나리오 예시

```
"대전 유성구 포트홀 영역을 찾아줘"          (도로시설·비전 연계)
"전국에서 화재가 가장 많은 지역은?"          (재난안전·순위)
"대전 미세먼지 현황 알려줘"                  (대기환경)
"인구가 많은 지역 순위 보여줘"               (인구)
"대전 노면상태별 교통사고를 보고서로 만들어줘" (교통안전·보고서)
```

## 탑재 데이터 (실 공공데이터)

7종의 실제 공공데이터를 **전국 17개 시도 + 대전 5개 자치구** 단위로 집계해 적재했다.
원본은 지점/사건 단위(최대 37.5만 행)라 `src/preprocess_real.py`가 지역 단위로 집계한다.

| 도메인 | 원본 CSV (루트) | 행수 | 집계본 (`data/raw/`) | 출처 |
|---|---|---|---|---|
| 생활안전 | `CCTV정보.csv` | 375,226 | `safety_cctv.csv` | data.go.kr 15013094 |
| 생활복지 | `무료와이파이정보.csv` | 91,865 | `public_wifi.csv` | data.go.kr 15013116 |
| 재난안전 | `소방청_연간화재통계_20241231.csv` | 37,614 | `fire_incidents.csv` | data.go.kr 15060386 |
| 인구 | `행정안전부_…주민등록 인구수_20260531.csv` | 3,618 | `population.csv` | data.go.kr 15097972 |
| 도로시설 | `한국도로공사_포트홀…_20241231.csv` | 33 | `korea_expressway_pothole.csv` | data.go.kr 15142616 |
| 교통안전 | `한국도로교통공단_노면상태별…csv` | 5 | `koroad_surface_accident.csv` | data.go.kr 15130420 |
| 교통안전 | `한국도로교통공단_사고유형별 도로종류별…csv` | 92 | `koroad_roadtype_accident.csv` | data.go.kr 15070288 |

> ⚠️ **원본 대용량 CSV(합계 ~110MB)는 저장소에 포함하지 않는다**(`.gitignore`).
> 실행에 필요한 **집계본 `data/raw/*.csv`는 커밋**되어 있어 clone 직후 `etl`부터 바로 동작한다.
> 원본부터 재현하려면 위 출처에서 받아 **프로젝트 루트**에 동일 파일명으로 두고
> `python src\preprocess_real.py`를 실행하면 된다.

## 전처리 파이프라인

```
(루트) 원본 CSV ──preprocess_real.py──▶ data/raw/*.csv ──etl.py──▶ normalized.jsonl ──ingest.py──▶ rag.db
        지점/사건 단위           시도/대전구 단위 집계      UnifiedDoc(263건)        SQLite + 임베딩
```

- **시도 정규화**: '경상북도'는 약칭 '경북'을 부분문자열로 포함하지 않으므로 정식 도명까지 별칭 처리.
- **대전 자치구**: `regions.py`가 해석 가능한 동/중/서/유성/대덕구는 시도 집계와 별도로 자치구 단위 행도 생성.
- KOROAD 교통사고 2종은 원본이 전국 단위(지역 분해 없음) → `region=전국`. 포트홀은 좌표가 없어 비전↔포트홀 공간조인 0건.

## 구조

```
data/raw/*.csv              다도메인 적재용 CSV (시도/대전 자치구 단위 집계, registry 스키마)
src/preprocess_real.py      ★실 공공데이터(루트 원본) → 시도+대전 자치구 집계 전처리
data/datasets/registry.json 데이터셋 매핑 레지스트리 ← 새 데이터셋은 여기에 config만 추가
data/normalized.jsonl       ETL 산출물 (UnifiedDoc 263건, 7개 도메인 — 실 공공데이터 집계)
src/schema.py               UnifiedDoc + DDL(domain/tags/region) + 이력/검수 테이블
src/regions.py              지역명↔코드 resolver (전국 시도 + 대전 자치구)
src/mapper.py               ★범용 매퍼: config + 원본행 → UnifiedDoc (코드 수정 불필요)
src/geo.py                  역지오코딩 + haversine 공간조인
src/etl.py                  레지스트리 기반 정규화 + 비전↔공공 공간조인
src/datago_client.py        data.go.kr OpenAPI 클라이언트
src/load_datago.py          실API 수집 → 매핑 → 적재 (원커맨드)
src/ingest.py               JSONL → SQLite 적재 + 임베딩 + 변경이력
src/retrieve.py             하이브리드 검색 + 재정렬 + 범용 집계 + 도메인 카탈로그
src/llm.py                  Gemini 3.5 Flash function-calling 루프
src/agent.py                도메인 중립 에이전트 (의도분석/도구호출/이력)
src/report.py               도메인 무관 .docx 보고서 자동 생성
src/server.py + web/        UI 백엔드 + 화면 프로토타입
run.ps1                     Windows 실행 헬퍼
```

## 빠른 시작 (Windows)

```powershell
git clone https://github.com/team-trie-prj/Hybrid_RAG.git
cd Hybrid_RAG
pip install -r requirements.txt          # 선택: 키 없이도 표준 라이브러리만으로 동작

.\run.ps1 etl        # 커밋된 집계본(data/raw)으로 적재 → rag.db 생성
.\run.ps1 ask "전국에서 화재가 가장 많은 지역은?"
```

## 실행 (Windows)

```powershell
.\run.ps1            # ETL → 적재 → 데모 5종 (다도메인 파이프라인)
.\run.ps1 etl        # 레지스트리 기반 ETL (집계본 CSV → 정규화 → 적재)
.\run.ps1 ask 전국에서 화재가 가장 많은 지역은?
.\run.ps1 report 대전 미세먼지 현황 요약          # .docx 생성
.\run.ps1 serve      # UI 서버 → http://localhost:8000
.\run.ps1 loadapi --all   # data.go.kr 실API 수집 (DATAGO_SERVICE_KEY 필요)
```

원본 대용량 CSV에서부터 재현하려면(선택): 위 [탑재 데이터](#탑재-데이터-실-공공데이터) 출처에서
받아 루트에 두고 `python src\preprocess_real.py`로 집계본을 다시 생성한 뒤 `.\run.ps1 etl`.

## 새 공공데이터셋 추가 (코드 수정 없이)

1. CSV를 `data/raw/`에 저장 (또는 API config 사용)
2. `data/datasets/registry.json`에 매핑 config 1개 추가:
   `dataset_id, source, domain, doc_type, title/text_template, region_field,
    period_field, metrics{표준명:컬럼}, source_file` (스키마는 `src/mapper.py` 주석 참고)
3. `.\run.ps1 etl`  → 즉시 통합 인덱스에 합류, 새 시나리오 검색 가능

실데이터/API 키 발급은 **[docs/SETUP_API_GEMINI.md](docs/SETUP_API_GEMINI.md)** 참고.

> ⚠️ 이 PC에서 `python`은 MS Store 스텁이고, anaconda python은 `sqlite3` DLL
> (`anaconda3\Library\bin`)이 PATH에 없으면 import 에러가 난다. `run.ps1`이
> 이 경로를 자동으로 PATH에 추가하므로 항상 `run.ps1`로 실행할 것.
> 수동 실행 시: `$env:PATH="C:\Users\user\anaconda3\Library\bin;"+$env:PATH`

## 실전 전환

| 프로토타입 | 실전 |
|---|---|
| SQLite 단일 파일 | PostgreSQL + PostGIS(geom) + pgvector(embedding) |
| 로컬 해시 임베딩 | Voyage `voyage-3` (VOYAGE_API_KEY) |
| 규칙 라우터 | Gemini 3.5 Flash function-calling (GEMINI_API_KEY) |
| 메모리 BM25 | OpenSearch / pg `tsvector` |

## 실사용 수준으로 확장 (로드맵)

- 데이터셋 수십~수백 종으로 확대 (registry config만 추가) + 실API 정기 수집(스케줄러)
- 저장소 실전화: SQLite → PostgreSQL + PostGIS(공간조인) + pgvector(벡터검색)
- 시군구 250여 개 전체 행정코드 + 행정경계 폴리곤(정밀 공간조인)
- 하이브리드 vs 단순 RAG 정량 비교(평가셋), 답변 근거 하이라이트
- 인증/권한, 사용량 로깅, 캐싱 등 운영 요소
