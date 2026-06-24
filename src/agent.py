"""도메인 중립 AI 에이전트: 공공데이터 + 사내 비전 통합 검색/분석.

특정 시나리오(포트홀)에 고정되지 않고, 적재된 어떤 도메인이든
질의 의도에 따라 검색·집계 도구를 호출한다.
- GEMINI_API_KEY 있으면 Gemini 3.1 Flash-Lite가 라우팅, 없으면 규칙 라우터 폴백.

도구:
  hybrid_search(query, domain?, region?, doc_type?, period?, k)
  aggregate(metric, group_by, domain?, region?, period?)
  list_domains()
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import llm
import regions
from retrieve import Index
from schema import (connect, ensure_schema, get_cached_answer, get_history,
                    get_trace, log_query, log_trace)

TOOLS = [
    {
        "name": "list_domains",
        "description": "적재된 데이터 도메인/종류 카탈로그를 반환한다. 어떤 데이터로 답할 수 있는지 모를 때 먼저 호출.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "hybrid_search",
        "description": "공공데이터+사내 비전 통합 인덱스에서 의미(임베딩)+키워드(BM25) 하이브리드 검색 후 재정렬. 위치/현황/사례 '찾기' 질의에 사용.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "자연어 검색어"},
                "domain": {"type": "string", "description": "교통안전|도로시설|대기환경|재난안전|인구|생활안전|생활복지 중 하나(선택)"},
                "region": {"type": "string", "description": "지역명(예: 대전, 서울, 유성구). 선택"},
                "doc_type": {"type": "string", "description": "세부 종류(선택)"},
                "period": {"type": "string", "description": "연도(예: 2023). 선택"},
                "k": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "aggregate",
        "description": "정형 통계 집계/순위. 지역·연도·범주별 합계나 비교('가장 많은', '순위', '통계') 질의에 사용.",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {"type": "string", "description": "합산 지표(count, death, injury, pm25, population, cctv_count 등)"},
                "group_by": {"type": "string", "description": "그룹 기준(region_name, domain, doc_type, surface, roadtype 등)"},
                "domain": {"type": "string"},
                "region": {"type": "string"},
                "period": {"type": "string"},
            },
            "required": ["metric", "group_by"],
        },
    },
]

SYSTEM = (
    "당신은 대한민국 공공데이터와 사내 비전(영상분석) 데이터를 검색·분석하는 지능형 에이전트다. "
    "사용자 자연어 질의의 의도를 파악해 도구를 호출한다. 적재 범위를 모르면 list_domains를 먼저 호출한다. "
    "위치·현황·사례 검색은 hybrid_search, 통계·순위·합계는 aggregate를 쓴다. "
    "지역이 지정되면 region으로 한정한다. 답변은 한국어로 간결하게, 반드시 출처(provenance.url)를 함께 제시한다. "
    "[중요·환각 억제] 도구 검색 결과에 근거가 없으면 사실을 지어내지 말고 "
    "'관련 정보를 찾을 수 없습니다.'라고 명시적으로 답한다. 검색 결과에 없는 수치·고유명사는 생성하지 않는다."
)

# 정보 부재 판정 임계값(질의어 적중률) 및 안내 문구 — FR-RAG-009 / AT-RAG-06
NO_RESULT_THRESHOLD = 0.10
NO_RESULT_MSG = ("관련 정보를 찾을 수 없습니다. 지식베이스(공공데이터·사내 비전)에 "
                 "해당 질의를 뒷받침할 근거 문서가 없어 답변을 생성하지 않았습니다.")

# 질의 의도 4종(요구사항 FR-RAG-002) → 처리 모듈명(FR-AGT-001 라우팅 메타)
INTENT_MODULE = {
    "문서검색": "RAG",
    "이미지분석": "VLM",
    "통계조회": "공공데이터",
    "보고서생성": "보고서",
}
IMAGE_KW = ("이미지", "사진", "영상", "그림", "업로드", "첨부", "라벨링",
            "바운딩", "bbox", "포트홀 영역", "탐지해", "탐지된")

DOMAIN_KW = {
    "대기환경": ["미세먼지", "초미세먼지", "대기", "오존", "pm10", "pm2.5", "pm", "공기"],
    "재난안전": ["화재", "소방", "재난", "불"],
    "인구": ["인구", "세대", "주민"],
    "생활안전": ["cctv", "방범", "감시"],
    "생활복지": ["와이파이", "wifi", "공공와이파이"],
    "교통안전": ["사고", "교통", "노면", "충돌", "사상", "도로종류"],
    "도로시설": ["포트홀", "파임", "균열", "포장", "노선", "도로현황", "비전", "탐지"],
}
DOMAIN_METRIC = {
    "교통안전": ("count", "사고건수"), "재난안전": ("count", "화재건수"),
    "대기환경": ("pm25", "초미세먼지(㎍/㎥)"), "인구": ("population", "인구수"),
    "도로시설": ("count", "건수"), "생활안전": ("cctv_count", "CCTV대수"),
    "생활복지": ("ap_count", "AP수"),
}


def _region_filter(region_text: str) -> dict:
    if not region_text:
        return {}
    r = regions.resolve(region_text)
    if r["sigungu_cd"]:
        return {"sigungu_cd": r["sigungu_cd"]}
    if r["sido_cd"]:
        return {"sido_cd": r["sido_cd"]}
    return {"region": region_text}


def _dispatch(idx: Index, name: str, args: dict):
    if name == "list_domains":
        return idx.domains()
    if name == "hybrid_search":
        flt = {}
        for k in ("domain", "doc_type", "period"):
            if args.get(k):
                flt[k] = args[k]
        flt.update(_region_filter(args.get("region", "")))
        return idx.hybrid_search(args["query"], filters=flt, k=int(args.get("k") or 6))
    if name == "aggregate":
        flt = {}
        for k in ("domain", "period"):
            if args.get(k):
                flt[k] = args[k]
        flt.update(_region_filter(args.get("region", "")))
        return idx.stats_query(args.get("metric") or "count",
                               args.get("group_by") or "region_name", flt)
    return {"error": f"unknown tool {name}"}


# ─────────────────────────────────────────── 질의 의도 분석 (폴백/로깅용)
def classify_intent(q: str, is_stats: bool, is_report: bool) -> str:
    """질의를 4종 의도로 분류 (FR-RAG-002).

    우선순위: 보고서생성 > 이미지분석 > 통계조회 > 문서검색.
    AT-RAG-01 예: '포트홀 보수 절차를 알려줘' → 문서검색.
    """
    ql = q.lower()
    if is_report:
        return "보고서생성"
    if any(k in ql for k in IMAGE_KW):
        return "이미지분석"
    if is_stats:
        return "통계조회"
    return "문서검색"


def analyze_intent(q: str) -> dict:
    ql = q.lower()
    domain = next((d for d, kws in DOMAIN_KW.items() if any(k in ql for k in kws)), None)
    reg = regions.resolve(q)
    is_stats = any(w in q for w in ("통계", "건수", "순위", "가장", "최다", "평균", "합계", "비교", "몇"))
    is_report = any(w in q for w in ("보고서", "요약", "정리", "브리핑"))
    intent = classify_intent(q, is_stats, is_report)
    return {
        "domain": domain,
        "region": reg["region_name"],
        "sido_cd": reg["sido_cd"], "sigungu_cd": reg["sigungu_cd"],
        "is_stats": is_stats,
        "is_report": is_report,
        "intent": intent,                      # 문서검색|이미지분석|통계조회|보고서생성
        "module": INTENT_MODULE[intent],       # 라우팅 모듈명 (응답 메타)
    }


def _summarize_result(result: Any) -> Any:
    """도구 결과 → 트레이스용 요약(JSON 직렬화 가능, 입력·결과 추적)."""
    if isinstance(result, list):
        head = []
        for r in result[:3]:
            if isinstance(r, dict):
                head.append(r.get("title") or r.get("group") or r.get("domain") or str(r)[:50])
            else:
                head.append(str(r)[:50])
        return {"n": len(result), "head": head}
    if isinstance(result, (int, float, str)):
        return {"value": result}
    return {"value": str(result)[:160]}


def _fallback(question: str, idx: Index) -> tuple[str, list[dict[str, Any]]]:
    """오프라인 규칙 라우터. (응답 텍스트, 단계별 트레이스)를 반환.

    질의어 적중률이 임계값 미만이고 통계 의도도 아니면 '정보 없음'으로 환각을 억제한다.
    """
    intent = analyze_intent(question)
    flt = {}
    if intent["domain"]:
        flt["domain"] = intent["domain"]
    if intent["sigungu_cd"]:
        flt["sigungu_cd"] = intent["sigungu_cd"]
    elif intent["sido_cd"]:
        flt["sido_cd"] = intent["sido_cd"]

    steps: list[dict[str, Any]] = []
    out = ["[오프라인 폴백 라우터 — GEMINI_API_KEY 설정 시 Gemini 3.1 Flash-Lite가 응답]"]
    out.append(f"의도: {intent['intent']} → {intent['module']} 모듈 "
               f"(domain={intent['domain'] or '전체'} / region={intent['region'] or '전국'})\n")

    want_search = (not intent["is_stats"]) or intent["is_report"]
    want_stats = intent["is_stats"] or intent["is_report"]

    hits: list[dict[str, Any]] = []
    if want_search:
        args = {"query": question, "filters": flt, "k": 5}
        hits = idx.hybrid_search(question, filters=flt, k=5)
        steps.append({"tool_name": "hybrid_search", "tool_input": args,
                      "result_summary": _summarize_result(hits)})

    # 환각 억제: 검색 의도인데 관련 근거가 없고 통계로도 답할 수 없으면 '정보 없음'
    if want_search and not want_stats and Index.best_relevance(hits) < NO_RESULT_THRESHOLD:
        out.append(NO_RESULT_MSG)
        return "\n".join(out), steps

    if want_search:
        out.append("◆ 하이브리드 검색 결과 (의미+키워드 융합 → 관련도 재정렬)")
        for h in hits:
            src = "사내 비전" if h["source"] == "gnsoft_vision" else "공공"
            out.append(f"  - [{src}/{h['domain']}] {h['title']} "
                       f"(유사도 {h.get('_similarity')}, 재정렬 {h.get('_rank_before')}→{h.get('_rank_after')}위) "
                       f"→ {h['provenance'].get('url')}")

    if want_stats:
        metric, label = DOMAIN_METRIC.get(intent["domain"] or "교통안전", ("count", "건수"))
        group_by = "surface" if "노면" in question else (
            "roadtype" if "도로종류" in question else "region_name")
        agg_flt = dict(flt)
        if group_by == "region_name":      # 지역 비교 시 지역 필터 해제
            agg_flt.pop("sido_cd", None); agg_flt.pop("sigungu_cd", None)
        rows = idx.stats_query(metric, group_by, agg_flt)
        steps.append({"tool_name": "aggregate",
                      "tool_input": {"metric": metric, "group_by": group_by, "filters": agg_flt},
                      "result_summary": _summarize_result(rows)})
        out.append(f"\n◆ 집계: {label} (그룹: {group_by})")
        for r in rows[:6]:
            out.append(f"  - {r['group']}: {int(r[metric]):,}")
    return "\n".join(out), steps


def _persist_trace(conn, run_id: str, ts: str, intent: dict,
                   steps: list[dict[str, Any]], answer: str) -> None:
    """단계별 실행 트레이스 기록: 의도분석 → 도구호출(입력·결과) → 최종답변 (AT-AGT-02)."""
    n = 1
    log_trace(conn, run_id, ts, n, "intent", module=intent["module"],
              detail={"intent": intent["intent"], "domain": intent["domain"],
                      "region": intent["region"]})
    for s in steps:
        n += 1
        log_trace(conn, run_id, ts, n, "tool_call", module=intent["module"],
                  tool_name=s.get("tool_name", ""), tool_input=s.get("tool_input"),
                  detail=s.get("result_summary"))
    log_trace(conn, run_id, ts, n + 1, "final", module=intent["module"],
              detail={"answer_preview": answer[:300]})


def ask(question: str, idx: Index | None = None, log: bool = True) -> str:
    idx = idx or Index()
    intent = analyze_intent(question)
    tools_used: list[str] = []
    steps: list[dict[str, Any]] = []

    # 캐시 우선: 동일 질의의 이전 Gemini 응답이 있으면 재사용(일일 한도 절약).
    cached = None
    if llm.gemini_available() and os.getenv("GEMINI_CACHE", "1") == "1":
        c = connect(idx.db_path)
        cached = get_cached_answer(c, question)
        c.close()

    if cached:
        answer = "[캐시된 Gemini 응답 — 일일 한도 절약을 위해 동일 질의 재사용]\n\n" + cached
        provider = "gemini-cache"
        tools_used = ["cache"]
    elif llm.gemini_available():
        try:
            answer, tools_used, steps = llm.run_agent(
                question, SYSTEM, TOOLS, lambda n, a: _dispatch(idx, n, a),
                summarize=_summarize_result)
            provider = "gemini"
        except Exception as e:
            msg = str(e)
            # 한도 소진이어도 동일 질의의 과거 Gemini 응답이 있으면 그것을 우선 사용
            c = connect(idx.db_path)
            prev = get_cached_answer(c, question)
            c.close()
            if prev:
                answer = "[캐시된 Gemini 응답 — 실시간 호출 실패로 이전 응답 재사용]\n\n" + prev
                provider = "gemini-cache"
                if log:
                    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    conn = connect(idx.db_path)
                    log_query(conn, ts, question, intent, ["cache"], answer, provider)
                    conn.close()
                return answer
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                note = ("[Gemini 무료 일일 한도 초과(프로젝트 단위) — 한도 리셋(다음 날) 또는 "
                        "결제 등급 전환이 필요합니다. 이전에 성공한 동일 질의는 캐시로 응답되며, "
                        "신규 질의는 아래 오프라인 라우터로 응답합니다]")
            elif "503" in msg or "UNAVAILABLE" in msg:
                note = "[Gemini 일시적 과부하(503) — 재시도 후에도 실패. 아래는 오프라인 라우터 응답]"
            else:
                note = f"[Gemini 호출 실패: {msg[:140]} … 아래는 오프라인 라우터 응답]"
            fb_text, steps = _fallback(question, idx)
            answer = note + "\n" + fb_text
            provider = "offline"
            tools_used = [s["tool_name"] for s in steps]
    else:
        answer, steps = _fallback(question, idx)
        provider = "offline"
        tools_used = [s["tool_name"] for s in steps]

    if log:
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn = connect(idx.db_path)
        ensure_schema(conn)  # agent_trace 등 신규 테이블 보장(기존 DB 마이그레이션)
        log_query(conn, ts, question, intent, tools_used, answer, provider)
        _persist_trace(conn, run_id=ts, ts=ts, intent=intent, steps=steps, answer=answer)
        conn.close()
    return answer


def history(idx: Index | None = None, limit: int = 20) -> list[dict]:
    idx = idx or Index()
    conn = connect(idx.db_path)
    rows = get_history(conn, limit)
    conn.close()
    return rows


def trace(run_id: str | None = None, idx: Index | None = None,
          limit: int = 200) -> list[dict]:
    """에이전트 실행 트레이스 조회 (FR-AGT-004). run_id 미지정 시 최근 단계 반환."""
    idx = idx or Index()
    conn = connect(idx.db_path)
    ensure_schema(conn)
    rows = get_trace(conn, run_id, limit)
    conn.close()
    return rows


if __name__ == "__main__":
    import sys
    print(ask(" ".join(sys.argv[1:]) or "대전 미세먼지 통계 보여줘"))
