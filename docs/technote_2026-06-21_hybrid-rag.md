# [테크노트] 대전 하이브리드 RAG 파이프라인 프로토타입 구축기

- 작성일: 2026-06-21
- 프로젝트: 지엔소프트 「생성형 AI 기반 지능형 정보 시스템」 — 하이브리드 RAG 파트
- 담당 범위: 공공데이터 선정 → 통합 데이터 구조 설계 → 하이브리드 RAG 파이프라인 → 프로토타입 검증
- 스택: Python, SQLite, 자체 구현 BM25/RRF, Gemini 3.5 Flash, (선택) Voyage 임베딩

---

## TL;DR

- 사내 Vision AI(포트홀 탐지) 데이터와 **대전 공공데이터**를 하나의 통합 스키마(`UnifiedDoc`)로 합치고,
  의미검색(임베딩) + 키워드검색(BM25)을 **RRF로 융합 → 최신성 재정렬**하는 하이브리드 RAG를 만들었다.
- LLM은 **Gemini 3.5 Flash** function calling으로 연동. 질의 의도에 따라 검색/통계 도구를 호출한다.
- **API 키 없이도** 규칙 라우터 + 로컬 해시 임베딩으로 데모가 끝까지 돌아간다(검증·시연용).
- 데모 3종("포트홀 찾기 → 통계 → 보고서") 오프라인 통과.

---

## 1. 배경 / 목표

제안서가 요구하는 하이브리드 RAG의 핵심은 *"단일 LLM·단순 RAG로는 검색 정확도·정보 최신성·도메인
특화 성능을 동시에 잡기 어렵다"* 는 문제의식이다. 그래서 다음 6단계 기능을 갖춰야 한다.

| # | 요구 기능 | 이번 구현 |
|---|---|---|
| 1 | 질의 의도 분석 / 라우팅 | ✅ Gemini 네이티브 + 규칙 폴백 |
| 2 | 하이브리드 검색 (BM25 + 벡터) | ✅ |
| 3 | 검색 결과 재정렬(re-ranking) | ✅ RRF + 최신성 가중 |
| 4 | 자동 요약 · 보고서 생성 | 🟡 텍스트 요약까지 |
| 5 | 외부 데이터 · 도구 호출(에이전트) | ✅ function calling |
| 6 | 정보 최신성 + 모듈 비교·검증 | 🟡 최신성만 반영, 비교는 TODO |

데모 지역은 **대전**으로 한정했다(사내 본사가 대전 유성구이기도 하고, 데이터 정합 검증이 쉬움).

---

## 2. 공공데이터 선정

서울에는 실시간 포트홀 위치 API(V2X)가 있지만 대전엔 없어서, **고속도로 포트홀 실측 + 대전 도로
인프라 + 노면상태 사고통계** 조합으로 구성했다.

| 역할 | 데이터셋 | dataset_id |
|---|---|---|
| 포트홀 실측 | 한국도로공사_포트홀 및 피해배상 현황 | 15142616 |
| 도로 인프라 | 대전광역시_도로 현황 | 15081752 |
| 도로 시설물 | 대전광역시_도로시설물 현황 | 15084031 |
| 사고 통계 | 도로교통공단_노면상태별 교통사고 통계 | 15130420 |

> 현재는 위 데이터셋을 본뜬 **샘플 JSONL 10건**으로 배선을 검증한 단계. 실제 CSV 다운로드 →
> 정규화 ETL은 다음 작업.

---

## 3. 통합 데이터 구조 (핵심 설계)

출처가 다른 모든 문서를 **하나의 레코드(`UnifiedDoc`)** 로 정규화하되, 모든 레코드가 동일한
**조인 키**를 갖도록 강제한 것이 설계의 핵심이다. 그래야 나중에 사내 비전 데이터가 들어와도
같은 키로 자연스럽게 붙는다.

```jsonc
{
  "doc_id": "pub-koex-2024-gb-001",
  "source": "korea_expressway",
  "doc_type": "pothole | road_infra | accident_stat | vision_detection",
  "title": "...", "text": "...",          // text = 임베딩/BM25 대상
  "geo":  { "lat": 36.35, "lng": 127.38,  // ── 공통 조인 키
            "sigungu_cd": "30200",        //    대전 자치구 행정코드
            "road_link_id": "1010001" },  //    표준노드링크
  "time": { "occurred_at": "2024-07-15", "period": "2024" },
  "metrics": { "count": 312 },            // 정형 집계용
  "provenance": { "dataset_id": "15142616", "url": "..." }  // 출처 인용
}
```

### 사내 비전 데이터 조인 전략

비전 데이터는 보통 `이미지ID + 클래스(pothole) + 좌표`만 있다. 이를 `geo`에 매핑하면 3가지로 조인된다.

1. **공간 조인** — 좌표 → PostGIS `ST_DWithin`으로 반경 N m 내 공공 포트홀/도로 매칭
2. **행정코드 조인** — 좌표 → `sigungu_cd` → 노면상태 사고통계(구 단위) 결합
3. **도로링크 조인** — 좌표 → `road_link_id` → 도로 인프라/소통정보 결합

→ `doc_type="vision_detection"` 레코드 한 줄로 합류함을 샘플로 실증했다.

---

## 4. 하이브리드 RAG 파이프라인

```
원천(공공 CSV/API, 사내 비전)
   → 정규화(UnifiedDoc) → 임베딩 → SQLite(정형 + 벡터)
   → [질의] (1)의도분석
          → (2)하이브리드 검색: Dense(코사인) ∥ Sparse(BM25)
          → (3)RRF 융합 → 재정렬(최신성 가중)
          → 메타필터(대전 sigungu_cd)
   → (5)Gemini 에이전트: hybrid_search / stats_query 도구 호출
   → (4)요약·보고서(+ provenance 출처 인용)
```

### 설계 포인트

- **RRF(Reciprocal Rank Fusion)**: `score = Σ 1/(60 + rank)`. 점수 스케일이 다른 dense/sparse를
  순위 기반으로 안전하게 합친다.
- **재정렬 + 최신성**: 융합 점수에 `(1 + 0.15 × 최신성)`을 곱해 최신 문서를 소폭 우대 → 제안서의
  "정보 최신성" 요구 반영.
- **도구화**: `hybrid_search`(찾기), `stats_query`(통계 집계)를 LLM 함수로 노출 → 질의 의도에 따라
  Gemini가 알아서 호출.

---

## 5. LLM 연동 — Gemini 3.5 Flash

`google-genai` SDK의 수동 function-calling 멀티턴 루프로 구현했다.

```python
from google import genai
from google.genai import types

client = genai.Client()  # GEMINI_API_KEY / GOOGLE_API_KEY 자동 인식
tools  = types.Tool(function_declarations=[...])   # name/description/parameters
config = types.GenerateContentConfig(system_instruction=SYSTEM, tools=[tools])

# 루프: generate_content → function_call 추출 → 함수 실행
#      → types.Part.from_function_response 로 결과 재전송 → 반복
```

- 모델 ID는 `GEMINI_MODEL` 환경변수로 덮어쓰기 가능(기본 `gemini-3.5-flash`).
- 키가 없으면 동일 도구를 호출하는 **규칙 기반 폴백 라우터**로 자동 전환 → 키 없이도 시연 가능.

---

## 6. 트러블슈팅 (Windows 환경)

직접 부딪힌 함정 기록.

1. **`python` 명령이 MS Store 스텁** — 비대화식 실행 시 "Python"만 출력하고 `exit 49`. 실제
   인터프리터는 anaconda 쪽을 써야 했다.
2. **`sqlite3` import 실패** — anaconda python에서 `_sqlite3` DLL 로드 실패.
   원인은 `anaconda3\Library\bin`(sqlite3.dll 위치)이 PATH에 없어서.
   → `run.ps1`이 이 경로를 PATH 앞에 자동 추가하도록 처리.
3. **한글 콘솔 깨짐** — `$env:PYTHONUTF8=1` + `[Console]::OutputEncoding=UTF8` 로 해결.
4. **Gemini 모델 ID** — 지식 컷오프 이후 출시 모델이라, 웹으로 `gemini-3.5-flash` 실재 확인 후
   환경변수로 교체 가능하게 설계.

---

## 7. 검증 결과 (2026-06-21)

- 데모 3종 오프라인 통과.
  - "대전 유성구 포트홀 찾아줘" → **사내 비전 탐지 → 경부선 포트홀 → 유성구 도로현황** 순으로 융합·재정렬
  - "노면상태별 통계" → 건조 4120 / 젖음 612 / 결빙 138 (정형 집계)
  - "요약 보고서" → 검색 + 통계 종합, 출처(data.go.kr URL) 인용
- `google-genai 2.9.0` 설치 후 Tool/Config/FunctionResponse 객체 구성 검증 완료(라이브 호출은 키 필요).

---

## 8. 다음 단계

- [ ] **(6) 하이브리드 vs 단순 RAG 정량 비교** — 제안서 핵심 산출물
- [ ] 실제 공공데이터 CSV → `UnifiedDoc` 정규화 ETL
- [ ] 사내 비전 실데이터 연계 + PostGIS 공간조인
- [ ] **(4) 보고서 산출물** — 텍스트 → .docx/PDF 템플릿
- [ ] 저장소 실전화: SQLite → PostgreSQL + PostGIS + pgvector

---

## 부록 — 실행 방법

```powershell
.\run.ps1            # 적재 + 데모 3종 (키 없이 오프라인 동작)
.\run.ps1 ask 대전 유성구 포트홀 찾아줘

# 실제 LLM/임베딩 승격
$env:GEMINI_API_KEY = "..."   # Gemini 3.5 Flash
$env:VOYAGE_API_KEY = "..."   # Voyage 임베딩(선택)
```

| 구성 요소 | 파일 |
|---|---|
| 통합 스키마 + DDL | `src/schema.py` |
| 임베딩 제공자 | `src/embeddings.py` |
| 적재 ETL | `src/ingest.py` |
| 하이브리드 검색 + 재정렬 + 집계 | `src/retrieve.py` |
| Gemini function-calling | `src/llm.py` |
| 에이전트(의도분석 + 도구호출) | `src/agent.py` |
| 데모 | `src/demo.py` |
