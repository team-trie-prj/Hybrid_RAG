# 개발 진행 내역 (공공데이터 하이브리드 RAG)

> 프로젝트: 지엔소프트 "생성형 AI 기반 지능형 정보 시스템" — 하이브리드 RAG 파트
> LLM: Gemini 3.5 Flash / 최종 갱신: 2026-06-22

> **v2 (범용화)**: 특정 시나리오(포트홀) 고정에서 **다도메인 범용 시스템**으로 확장.
> - config 기반 범용 적재: 새 데이터셋은 `data/datasets/registry.json`에 매핑 config만 추가(코드 0).
> - 적재: 10개 데이터셋 / 7개 도메인(교통안전·도로시설·대기환경·재난안전·인구·생활안전·생활복지) / 51건.
> - 도메인 중립 에이전트: `hybrid_search` / `aggregate` / `list_domains` 도구, 의도·지역·도메인 자동 라우팅.
> - 실API 로더(`load_datago.py`) + 키 발급/Gemini 설정: [SETUP_API_GEMINI.md](SETUP_API_GEMINI.md).
> 최신 사용법·구조는 [README](../README.md) 기준. 아래는 초기(v1) 기록.

## 1. 제안서가 요구하는 하이브리드 RAG 기능 ↔ 구현 현황

단일 LLM·단순 RAG의 한계(검색 정확도·정보 최신성·도메인 특화 성능 동시 확보 곤란)를 극복하는 것이 목표.

| # | 요구 기능 | 구현 위치 | 상태 |
|---|---|---|---|
| 1 | 질의 의도 분석 / 라우팅 | `agent.py` (Gemini 네이티브 + `analyze_intent` 폴백) | ✅ 기본 |
| 2 | 하이브리드 검색 (BM25 + 벡터) | `retrieve.py` `hybrid_search` | ✅ |
| 3 | 검색 결과 재정렬(re-ranking) | `retrieve.py` (RRF 융합 + 최신성 가중 재정렬) | ✅ 기본 |
| 4 | 자동 요약 · 보고서 생성 | `report.py` (.docx) + `agent.py` 요약 | ✅ .docx 산출 |
| 5 | 외부 데이터 · 도구 호출(에이전트) | `agent.py` `TOOLS` + `llm.py` function-calling | ✅ |
| 6 | 정보 최신성 + 모듈 비교·검증 | 최신성=재정렬에 반영 / 비교검증=미착수 | 🟡 일부 |

추가 구현(요구사항 확장): 실데이터 ETL·공간조인, 데이터/이력 관리 체계, UI/UX 화면 프로토타입.

## 2. 구성 요소

```
data/raw/*.csv              실데이터 스키마 원본 CSV (도로공사 포트홀/노면사고/도로현황/비전탐지)
data/normalized.jsonl       ETL 산출물 (UnifiedDoc 19건)
src/schema.py               UnifiedDoc + DDL + query_history/doc_change_log/review_status
src/embeddings.py           임베딩 제공자 (Voyage / 로컬해시 폴백)
src/geo.py                  역지오코딩(→대전 자치구) + haversine 공간조인
src/etl.py                  CSV → UnifiedDoc 정규화 + 비전↔공공 공간조인
src/datago_client.py        data.go.kr OpenAPI 클라이언트 + 인증키 발급 가이드
src/ingest.py               JSONL → SQLite 적재 + 임베딩 + 변경이력 로깅
src/retrieve.py             (2)하이브리드 검색 + (3)재정렬 + 정형 집계(stats_query)
src/llm.py                  Gemini 3.5 Flash function-calling 루프 (google-genai)
src/agent.py                (1)의도 분석 + (5)도구 호출 + 질의이력 로깅 + 폴백
src/report.py               (4)검색+통계 → .docx 보고서 자동 생성
src/server.py + web/        UI 백엔드(stdlib http) + 화면 프로토타입
src/demo.py / run.ps1       데모 / Windows 실행 헬퍼
```

## 3. 데이터 흐름

```
원천(공공 CSV/API, 사내 비전 CSV)
   → etl.py 정규화(UnifiedDoc) + 역지오코딩 + 비전↔공공 공간조인
   → ingest.py 임베딩 + SQLite(정형+벡터) 적재 + 변경이력
   → [질의] 의도분석 → 하이브리드검색(Dense+Sparse, RRF) → 재정렬(최신성)
   → 메타필터(대전) → Gemini 에이전트(검색·통계 도구) → 질의이력 로깅
   → 요약 / report.py .docx 보고서(+출처)  ··· 모두 web UI로 노출
```

## 4. 통합 데이터 구조 (조인 키 중심)

모든 출처를 `UnifiedDoc` 하나로 정규화. 핵심은 공통 조인 키:
- 공간: `lat/lng`, `sigungu_cd`(대전 자치구 행정코드), `road_link_id`(표준노드링크)
- 시간: `occurred_at`, `period`
- 수치: `metrics`(JSON, 집계용) / 추적: `provenance`(데이터셋ID·URL)

→ 사내 비전 데이터는 `doc_type="vision_detection"`으로 좌표만 매핑하면 동일 테이블에
합류하며, 공간/행정코드/도로링크 3방식으로 공공데이터와 조인된다. (샘플 1건으로 실증)

## 5. 사용한 공공데이터 (대전)

| 역할 | 데이터셋 | dataset_id |
|---|---|---|
| 포트홀 실측 | 한국도로공사_포트홀 및 피해배상 현황 | 15142616 |
| 도로 인프라 | 대전광역시_도로 현황 | 15081752 |
| 도로 시설물 | 대전광역시_도로시설물 현황 | 15084031 |
| 사고 통계 | 도로교통공단_노면상태별 교통사고 통계 | 15130420 |

> `data/raw/`의 CSV는 위 데이터셋의 **실제 컬럼을 본뜬 샘플**. 실제 파일/oAPI 교체는
> README "실제 공공데이터 연동" 및 `src/datago_client.py` 가이드 참조.

## 6. 실행 / 검증

```powershell
.\run.ps1            # ETL → 적재 → 데모 3종 (키 없이 오프라인 동작)
.\run.ps1 etl        # 실데이터 ETL (CSV → 정규화 → 적재)
.\run.ps1 report 대전 포트홀 요약 보고서   # .docx 생성
.\run.ps1 serve      # UI → http://localhost:8000
```

검증됨(2026-06-22):
- ETL 19건 정규화(공공 15 + 비전 4) + 비전↔공공 공간조인 4건, SQLite 적재 OK.
- 데이터/이력: doc_change_log 38건, query_history 로깅, review_status 컬럼 동작.
- 보고서: .docx 자동 생성(검색 6건 표 + 노면통계 표 + 출처) OK.
- UI: 서버 기동 후 /api/ask·/api/report·/api/history 동작, 화면 렌더 스크린샷 확인.
- "유성구 포트홀" 질의 시 사내 비전(월드컵대로) → 유성구 도로현황 순 융합·재정렬 확인.
- Gemini SDK(google-genai 2.9.0) 객체 구성 검증(라이브 호출은 `GEMINI_API_KEY` 필요).

## 7. 환경 설정 (LLM/임베딩 승격)

| 변수 | 용도 | 기본/폴백 |
|---|---|---|
| `GEMINI_API_KEY` (또는 `GOOGLE_API_KEY`) | Gemini 3.5 Flash 에이전트 | 없으면 규칙 라우터 |
| `GEMINI_MODEL` | 모델 ID 덮어쓰기 | `gemini-3.5-flash` |
| `VOYAGE_API_KEY` | Voyage 임베딩 | 없으면 로컬 해시 |

## 8. 남은 작업

- (6) 모듈 비교·검증: 하이브리드 vs 단순 RAG 정량 비교 (제안서 핵심 산출물)
- 실제 data.go.kr 파일/oAPI로 `data/raw/` 교체 (현재는 실스키마 샘플)
- 저장소 실전화: SQLite → PostgreSQL + PostGIS(공간조인) + pgvector
- VLM 연계(이미지 자동 라벨링), 도메인 파인튜닝 검토
