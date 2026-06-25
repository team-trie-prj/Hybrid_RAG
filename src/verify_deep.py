# -*- coding: utf-8 -*-
"""심화 검증: 의도분석(다양한 시나리오) · 키워드/벡터 검색 분리 · FR-AGT · NFR.

실행:  python verify_deep.py
- Gemini 키가 있으면 FR-AGT 라이브 1건을 실제 호출(쿼터 절약 위해 최소화).
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import agent
import llm
from retrieve import Index, _tokenize

idx = Index()


def sec(t):
    print("\n" + "═" * 72 + f"\n  {t}\n" + "═" * 72)


# ─────────────────────────────── 1) FR-RAG-002 의도분석 다양한 시나리오
sec("1) FR-RAG-002 질의 의도 분석 — 다양한 시나리오 (intent → module)")
SCENARIOS = [
    "포트홀 보수 절차를 알려줘",
    "대전 유성구 도로 파손 사례를 찾아줘",
    "도로 균열 대응 방법이 궁금해",
    "전국에서 화재가 가장 많은 지역은?",
    "대전 미세먼지 통계 보여줘",
    "인구가 많은 지역 순위 알려줘",
    "노면상태별 교통사고 건수 비교해줘",
    "이 이미지에서 포트홀을 탐지해줘",
    "업로드한 사진 분석해줘",
    "도로 영상에서 위험요소 라벨링 해줘",
    "대전 노면상태별 교통사고를 요약해서 보고서로 만들어줘",
    "화재 현황 정리해서 브리핑 자료 만들어줘",
    "공공데이터포털 기반 대전 화재 통계를 조회해줘",
    "서울 대기질이 어떤지 설명해줘",
    "양자컴퓨터 가격을 알려줘",
]
for q in SCENARIOS:
    it = agent.analyze_intent(q)
    print(f"  {it['intent']:>6} → {it['module']:<6} | domain={it['domain'] or '-':<5} "
          f"region={it['region'] or '전국':<8} | {q}")

# ─────────────────────────────── 2) 키워드(BM25) / 벡터(Dense) 검색 분리 검증
sec("2) FR-RAG-003/004/005 키워드(BM25) · 벡터(Dense) · 하이브리드 분리 검증")
for q in ["대전 유성구 포트홀", "전국 화재 현황"]:
    bm = idx._bm25_scores(q)
    dn = idx._dense_scores(q)
    bm_top = sorted(bm.items(), key=lambda kv: kv[1], reverse=True)[:3]
    dn_top = sorted(dn.items(), key=lambda kv: kv[1], reverse=True)[:3]
    print(f"\n  질의: '{q}'")
    print(f"   [키워드 BM25 단독] 상위 (점수>0 {sum(1 for v in bm.values() if v>0)}건)")
    for did, s in bm_top:
        print(f"      {s:6.3f}  {idx.docs[did]['title'][:40]}")
    print(f"   [벡터 Dense 단독] 상위 (코사인)")
    for did, s in dn_top:
        print(f"      {s:6.3f}  {idx.docs[did]['title'][:40]}")
    print(f"   [하이브리드 RRF+재정렬] 상위")
    for h in idx.hybrid_search(q, k=3):
        print(f"      sim={h['_similarity']}  dense#{h['_dense_rank']} sparse#{h['_sparse_rank']}  {h['title'][:40]}")

# ─────────────────────────────── 3) FR-AGT 오케스트레이션 (라이브 Gemini 1건)
sec("3) FR-AGT-001~004 에이전트 오케스트레이션 (Function Calling)")
print(f"  Gemini 사용 가능: {llm.gemini_available()} | 모델: {llm.MODEL}")
complex_q = "공공데이터로 전국 화재가 가장 많은 지역을 조회해서 요약 보고서로 만들어줘"
t0 = time.time()
ans = agent.ask(complex_q, idx)
dt = time.time() - t0
print(f"  질의: {complex_q}")
print(f"  응답시간: {dt:.2f}s")
print(f"  응답(head): {ans[:200]}")
tr = agent.trace(None, idx, limit=8)
# 최근 run 추출
if tr:
    run_id = tr[0]["run_id"]
    steps = [t for t in agent.trace(run_id, idx)]
    print(f"  실행 트레이스 ({len(steps)}단계, run={run_id}):")
    for s in steps:
        extra = f" tool={s['tool_name']} in={s['tool_input']}" if s["step_type"] == "tool_call" else ""
        print(f"     #{s['step_no']} {s['step_type']}{extra}")

# ─────────────────────────────── 4) NFR 성능 (검색 5초 / 보고서 15초)
sec("4) NFR-PERF 성능 — 검색 응답시간 / 보고서 생성시간")
import report as report_mod
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
times = []
for q in ["대전 포트홀", "전국 화재 순위", "서울 대기질", "인구 순위", "노면상태 교통사고"]:
    t0 = time.time(); idx.hybrid_search(q, k=6); times.append(time.time() - t0)
times.sort()
p90 = times[int(len(times) * 0.9) - 1]
print(f"  하이브리드 검색 응답: 평균 {sum(times)/len(times)*1000:.0f}ms, P90 {p90*1000:.0f}ms (목표<5000ms) "
      f"→ {'PASS' if p90 < 5 else 'FAIL'}")
t0 = time.time()
report_mod.generate_report("대전 노면상태별 교통사고 요약", idx, os.path.join(ROOT, "report_output.docx"))
rt = time.time() - t0
print(f"  보고서(.docx) 생성: {rt:.2f}s (목표<15s) → {'PASS' if rt < 15 else 'FAIL'}")

# ─────────────────────────────── 5) NFR-SEC 보안 (하드코딩 키 스캔)
sec("5) NFR-SEC 보안 — 소스 하드코딩 비밀키 스캔")
import re
SRC = os.path.dirname(os.path.abspath(__file__))
leak = []
key_pat = re.compile(r"(AIza[0-9A-Za-z_\-]{30,}|sk-[0-9A-Za-z]{20,}|serviceKey\s*=\s*[\"'][^\"']{20,})")
for fn in os.listdir(SRC):
    if fn.endswith(".py"):
        with open(os.path.join(SRC, fn), encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                if key_pat.search(line):
                    leak.append(f"{fn}:{i}")
print(f"  하드코딩 키 의심: {len(leak)}건 {leak if leak else '(없음)'} → {'PASS' if not leak else 'FAIL'}")
print(f"  .env 커밋 제외: {'PASS' if '.env' in open(os.path.join(ROOT, '.gitignore'), encoding='utf-8').read() else 'FAIL'}")

# ─────────────────────────────── 6) NFR-REL 환각 억제 (정보 부재)
sec("6) NFR-REL-001 / AT-NFR-02 환각 억제 — 근거 외 사실 생성 0건")
miss, _ = agent._fallback("화성 토양의 철분 함량을 알려줘", idx)
ok = agent.NO_RESULT_MSG[:15] in miss
print(f"  지식베이스 무관 질의 → 정보없음 응답: {'PASS' if ok else 'FAIL'}")
print(f"    응답: {miss.splitlines()[-1][:60]}")

sec("심화 검증 완료")
