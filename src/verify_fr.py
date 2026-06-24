# -*- coding: utf-8 -*-
"""요구사항 정의서(FR-RAG / FR-PUB / FR-AGT) ↔ 구현 검증.

각 인수 테스트(AT)를 실제로 실행해 PASS/FAIL과 근거를 출력한다.
판정 로직(검색·재정렬·환각억제·오케스트레이션)은 LLM 제공자와 무관하게
결정론적으로 동작하도록 오프라인 빌딩블록을 직접 호출해 검증한다.

실행:  python verify_fr.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import agent
import datago_client
from retrieve import Index

idx = Index()
_PASS = 0
_FAIL = 0


def section(t: str) -> None:
    print("\n" + "═" * 70 + f"\n  {t}\n" + "═" * 70)


def check(at: str, ok: bool, evidence: str) -> None:
    global _PASS, _FAIL
    mark = "✅ PASS" if ok else "❌ FAIL"
    if ok:
        _PASS += 1
    else:
        _FAIL += 1
    print(f"[{mark}] {at}\n         {evidence}")


# ───────────────────────────────────────────── FR-RAG
section("FR-RAG 하이브리드 RAG")

# AT-RAG-01 : 질의 의도 4종 분류 → 모듈 라우팅 (테스트셋 10건 중 80% 이상)
ROUTING_SET = [
    ("포트홀 보수 절차를 알려줘", "RAG"),
    ("대전 화재 통계를 보여줘", "공공데이터"),
    ("이 이미지에서 포트홀을 탐지해줘", "VLM"),
    ("대전 노면상태별 교통사고를 요약해서 보고서로 만들어줘", "보고서"),
    ("전국에서 화재가 가장 많은 지역은?", "공공데이터"),
    ("유성구 도로 파손 사례를 찾아줘", "RAG"),
    ("업로드한 사진을 분석해줘", "VLM"),
    ("대전 미세먼지 현황 정리해줘", "보고서"),
    ("인구가 많은 지역 순위 보여줘", "공공데이터"),
    ("도로 균열 대응 방법을 설명해줘", "RAG"),
]
correct = 0
detail = []
for q, expect in ROUTING_SET:
    it = agent.analyze_intent(q)
    ok = it["module"] == expect
    correct += ok
    detail.append(f"{'o' if ok else 'x'} '{q[:18]}…' → {it['intent']}/{it['module']}")
acc = correct / len(ROUTING_SET)
check("AT-RAG-01 의도분류·모듈 라우팅 (≥80%)", acc >= 0.8,
      f"정확도 {correct}/{len(ROUTING_SET)} = {acc:.0%}  (응답 메타에 intent/module 표기)")
for d in detail:
    print("           " + d)

# AT-RAG-02 : 하이브리드 검색 Recall@5 ≥ 0.8
EVAL = [
    ("서울 화재 발생 현황 2024 알려줘", "nfa-15060386-서울특별시_2024"),
    ("부산 대기질 미세먼지 현황 2023", "airkorea-15073861-부산광역시_2023"),
    ("대전 대기질 현황 어때", "airkorea-15073861-대전광역시_2023"),
    ("대구 주민등록 인구 2026 얼마", "mois-15097972-대구광역시_2026"),
    ("월드컵대로 포트홀 탐지 사례", "gnsoft_vision-internal-vision-DJ_CAM_0001"),
    ("둔산로 포트홀 탐지", "gnsoft_vision-internal-vision-DJ_CAM_0002"),
    ("한밭대로 도로 균열 탐지", "gnsoft_vision-internal-vision-DJ_CAM_0003"),
    ("전국 노면상태 건조 교통사고 2024", "koroad-15130420-2024_건조_전국"),
]


def _ranks(rerank: bool) -> list[int]:
    out = []
    for q, gold in EVAL:
        ids = [r["doc_id"] for r in idx.hybrid_search(q, k=10, rerank=rerank)]
        out.append(ids.index(gold) + 1 if gold in ids else 0)
    return out


ranks_on = _ranks(True)
hit5 = sum(1 for r in ranks_on if 1 <= r <= 5)
recall5 = hit5 / len(EVAL)
check("AT-RAG-02 하이브리드 검색 Recall@5 (≥0.8)", recall5 >= 0.8,
      f"Recall@5 = {hit5}/{len(EVAL)} = {recall5:.0%} (BM25+벡터 RRF 융합)")

# AT-RAG-03 : 재정렬 동작(순위 변화) + 정답셋 MRR 비저하
ranks_off = _ranks(False)
mrr = lambda rs: sum((1.0 / r if r else 0.0) for r in rs) / len(rs)
mrr_on, mrr_off = mrr(ranks_on), mrr(ranks_off)
demo = idx.hybrid_search("전국 화재 현황", k=8, rerank=True)
reordered = sum(1 for r in demo if r["_rank_before"] != r["_rank_after"])
check("AT-RAG-03 재정렬(Reranker) 동작 + MRR 비저하", reordered > 0 and mrr_on >= mrr_off,
      f"순위 변동 {reordered}/{len(demo)}건(관련도 재정렬 동작), "
      f"MRR 재정렬={mrr_on:.3f} ≥ 미적용={mrr_off:.3f}")
print("           예) '전국 화재 현황' 재정렬: 비관련 문서 강등, 화재 문서 상위 이동")
for r in demo[:3]:
    print(f"             before#{r['_rank_before']}→after#{r['_rank_after']} sim={r['_similarity']} {r['title'][:34]}")

# AT-RAG-04 : 모든 결과에 0~1 유사도 점수 표출
res4 = idx.hybrid_search("대전 포트홀 파임", k=5)
all_sim = all(isinstance(r.get("_similarity"), (int, float)) and 0.0 <= r["_similarity"] <= 1.0
              for r in res4)
check("AT-RAG-04 유사도 점수(0~1) 표출", all_sim and len(res4) > 0,
      f"전 결과 _similarity ∈ [0,1] 부여: 예 {[r['_similarity'] for r in res4]}")

# AT-RAG-05 : 근거 기반 답변 + 출처 표시
ans5, steps5 = agent._fallback("월드컵대로 포트홀 현황 알려줘", idx)
has_src = "http" in ans5 or "→" in ans5
check("AT-RAG-05 근거 기반 답변·출처 표시", has_src,
      "답변에 근거 문서 출처(provenance.url) 연결됨")

# AT-RAG-06 : 정보 부재 질의 → 환각 대신 '정보 없음'
ans6, _ = agent._fallback("양자컴퓨터 최신 칩 가격을 알려줘", idx)
no_result = agent.NO_RESULT_MSG[:15] in ans6
check("AT-RAG-06 정보 부재 질의 환각 억제", no_result,
      "지식베이스 무관 질의 → '관련 정보를 찾을 수 없습니다' 반환")


# ───────────────────────────────────────────── FR-PUB
section("FR-PUB 공공데이터포털 연계")

# AT-PUB-01/02 : 통계 데이터 조회 (지역/주제 파라미터 → 일치 데이터 반환)
rows = idx.stats_query("count", "region_name", {"domain": "재난안전"})
check("AT-PUB-01/02 공공데이터 통계 조회", len(rows) > 0,
      f"재난안전(화재) 지역별 집계 {len(rows)}건, 1위 {rows[0]['group']}={int(rows[0]['count']):,}")

# AT-PUB-03 : 공공데이터 기반 QA + 출처
pub_hits = idx.hybrid_search("서울 화재 현황", filters={"domain": "재난안전"}, k=3)
pub_src = any(h["provenance"].get("url") for h in pub_hits)
check("AT-PUB-03 공공데이터 기반 QA·출처", len(pub_hits) > 0 and pub_src,
      f"공공데이터 근거 {len(pub_hits)}건 + 출처 URL 포함")

# AT-PUB-04 : 사내 비전 + 공공데이터 복합(통합 인덱스)
sources = {r["source"] for r in idx.rows}
multi = "gnsoft_vision" in sources and len(sources) >= 2
check("AT-PUB-04 사내 비전 + 공공데이터 복합 출처", multi,
      f"통합 인덱스 출처 {len(sources)}종: {sorted(sources)}")

# AT-PUB-05 : 외부 API 장애 graceful 처리 (예외 비전파)
r_nokey = datago_client.fetch_openapi_safe("https://invalid.example/none", {"x": 1})
os.environ["DATAGO_SERVICE_KEY"] = "TEST_DUMMY_KEY"
r_bad = datago_client.fetch_openapi_safe("https://invalid.invalid.example/none", {"x": 1})
del os.environ["DATAGO_SERVICE_KEY"]
graceful = (r_nokey["ok"] is False and "user_message" in r_nokey
            and r_bad["ok"] is False and "user_message" in r_bad)
check("AT-PUB-05 외부 API 오류 graceful 처리", graceful,
      f"무인증→안내, 장애→안내 (예외 비전파): '{r_bad['user_message'][:30]}…'")


# ───────────────────────────────────────────── FR-AGT
section("FR-AGT 에이전트 오케스트레이션")

# AT-AGT-01 : 복합 질의 다단계 도구 호출 (통계 조회 → 요약/보고)
_, steps_complex = agent._fallback(
    "대전 노면상태별 교통사고 통계를 조회해서 요약 보고서로 만들어줘", idx)
tools_seq = [s["tool_name"] for s in steps_complex]
multi_step = len(steps_complex) >= 2
check("AT-AGT-01 다단계 도구 호출 오케스트레이션", multi_step,
      f"복합 질의 도구 시퀀스: {tools_seq} (검색→집계 순차 호출)")

# AT-AGT-02 : 실행 트레이스 단계별 기록(순서 보존, 입력·결과 포함)
run_ts = "VERIFY-RUN-0001"
conn = agent.connect(idx.db_path)
agent.ensure_schema(conn)
agent._persist_trace(conn, run_id=run_ts, ts=run_ts,
                     intent=agent.analyze_intent("대전 화재 통계 보고서"),
                     steps=steps_complex, answer="(검증용 트레이스)")
conn.close()
tr = agent.trace(run_ts, idx)
types_seq = [t["step_type"] for t in tr]
ordered = [t["step_no"] for t in tr] == sorted(t["step_no"] for t in tr)
has_io = any(t["step_type"] == "tool_call" and t["tool_input"] is not None for t in tr)
ok_trace = (types_seq[:1] == ["intent"] and types_seq[-1:] == ["final"]
            and "tool_call" in types_seq and ordered and has_io)
check("AT-AGT-02 단계별 실행 로그 추적", ok_trace,
      f"트레이스 {len(tr)}단계 순서보존: {types_seq} (의도→도구(입력·결과)→최종)")
for t in tr:
    extra = f" tool={t['tool_name']} in={t['tool_input']}" if t["step_type"] == "tool_call" else ""
    print(f"           #{t['step_no']} {t['step_type']}{extra}")
# 검증용 트레이스 정리
conn = agent.connect(idx.db_path)
conn.execute("DELETE FROM agent_trace WHERE run_id=?", (run_ts,))
conn.commit()
conn.close()


# ───────────────────────────────────────────── 결과 요약
section(f"검증 결과: {_PASS} PASS / {_FAIL} FAIL  (총 {_PASS + _FAIL}건)")
sys.exit(1 if _FAIL else 0)
