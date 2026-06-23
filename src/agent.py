"""도메인 중립 AI 에이전트: 공공데이터 + 사내 비전 통합 검색/분석.

특정 시나리오(포트홀)에 고정되지 않고, 적재된 어떤 도메인이든
질의 의도에 따라 검색·집계 도구를 호출한다.
- GEMINI_API_KEY 있으면 Gemini 3.5 Flash가 라우팅, 없으면 규칙 라우터 폴백.

도구:
  hybrid_search(query, domain?, region?, doc_type?, period?, k)
  aggregate(metric, group_by, domain?, region?, period?)
  list_domains()
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import llm
import regions
from retrieve import Index
from schema import connect, get_history, log_query

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
    "지역이 지정되면 region으로 한정한다. 답변은 한국어로 간결하게, 반드시 출처(provenance.url)를 함께 제시한다."
)

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
def analyze_intent(q: str) -> dict:
    ql = q.lower()
    domain = next((d for d, kws in DOMAIN_KW.items() if any(k in ql for k in kws)), None)
    reg = regions.resolve(q)
    return {
        "domain": domain,
        "region": reg["region_name"],
        "sido_cd": reg["sido_cd"], "sigungu_cd": reg["sigungu_cd"],
        "is_stats": any(w in q for w in ("통계", "건수", "순위", "가장", "최다", "평균", "합계", "비교", "몇")),
        "is_report": any(w in q for w in ("보고서", "요약", "정리", "브리핑")),
    }


def _fallback(question: str, idx: Index) -> str:
    intent = analyze_intent(question)
    flt = {}
    if intent["domain"]:
        flt["domain"] = intent["domain"]
    if intent["sigungu_cd"]:
        flt["sigungu_cd"] = intent["sigungu_cd"]
    elif intent["sido_cd"]:
        flt["sido_cd"] = intent["sido_cd"]

    out = ["[오프라인 폴백 라우터 — GEMINI_API_KEY 설정 시 Gemini 3.5 Flash가 응답]"]
    out.append(f"의도: domain={intent['domain'] or '전체'} / region={intent['region'] or '전국'}\n")

    if not intent["is_stats"] or intent["is_report"]:
        out.append("◆ 하이브리드 검색 결과 (의미+키워드 융합 → 재정렬)")
        for h in idx.hybrid_search(question, filters=flt, k=5):
            src = "사내 비전" if h["source"] == "gnsoft_vision" else "공공"
            out.append(f"  - [{src}/{h['domain']}] {h['title']}  → {h['provenance'].get('url')}")

    if intent["is_stats"] or intent["is_report"]:
        metric, label = DOMAIN_METRIC.get(intent["domain"] or "교통안전", ("count", "건수"))
        group_by = "surface" if "노면" in question else (
            "roadtype" if "도로종류" in question else "region_name")
        agg_flt = dict(flt)
        if group_by == "region_name":      # 지역 비교 시 지역 필터 해제
            agg_flt.pop("sido_cd", None); agg_flt.pop("sigungu_cd", None)
        rows = idx.stats_query(metric, group_by, agg_flt)
        out.append(f"\n◆ 집계: {label} (그룹: {group_by})")
        for r in rows[:6]:
            out.append(f"  - {r['group']}: {int(r[metric]):,}")
    return "\n".join(out)


def ask(question: str, idx: Index | None = None, log: bool = True) -> str:
    idx = idx or Index()
    intent = analyze_intent(question)
    tools_used: list[str] = []

    if llm.gemini_available():
        try:
            answer, tools_used = llm.run_agent(
                question, SYSTEM, TOOLS, lambda n, a: _dispatch(idx, n, a))
            provider = "gemini"
        except Exception as e:
            answer = f"[Gemini 호출 실패: {e}]\n" + _fallback(question, idx)
            provider = "offline"
    else:
        answer = _fallback(question, idx)
        provider = "offline"
        if not intent["is_stats"] or intent["is_report"]:
            tools_used.append("hybrid_search")
        if intent["is_stats"] or intent["is_report"]:
            tools_used.append("aggregate")

    if log:
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn = connect(idx.db_path)
        log_query(conn, ts, question, intent, tools_used, answer, provider)
        conn.close()
    return answer


def history(idx: Index | None = None, limit: int = 20) -> list[dict]:
    idx = idx or Index()
    conn = connect(idx.db_path)
    rows = get_history(conn, limit)
    conn.close()
    return rows


if __name__ == "__main__":
    import sys
    print(ask(" ".join(sys.argv[1:]) or "대전 미세먼지 통계 보여줘"))
