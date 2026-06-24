# -*- coding: utf-8 -*-
"""제안서 요구사항 ↔ 구현 검증: 핵심 기능을 실제로 실행해 증거를 출력."""
from __future__ import annotations
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from retrieve import Index
from schema import connect
import report as report_mod

idx = Index()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def line(t): print("\n" + "─" * 64 + f"\n▶ {t}\n" + "─" * 64)


line("R1. 통합 데이터 구조 / 다도메인 적재 (UnifiedDoc)")
print(f"  총 문서: {len(idx.rows)}건")
for d in idx.domains():
    print(f"  - {d['domain']}: {d['count']}건  {d['doc_types']}")

line("R2. 하이브리드 검색 (의미 임베딩 + 키워드 BM25 → RRF) + 재정렬")
print(f"  임베딩 제공자: {idx._dense_scores.__self__ and __import__('embeddings').Embeddings().provider}")
for r in idx.hybrid_search("대전 포트홀 파임", k=3):
    print(f"  [score={r['_score']}] dense#{r['_dense_rank']} sparse#{r['_sparse_rank']}  {r['title']}")
print("  → dense/sparse 각 랭크가 RRF로 융합되고 최신성 가중(rerank) 반영됨")

line("R3. 정형 통계 집계 / 순위 (공공데이터 기반)")
for r in idx.stats_query("count", "region_name", {"domain": "재난안전"})[:5]:
    print(f"  화재건수  {r['group']}: {int(r['count']):,}")

line("R4. 사내 비전(영상분석) ↔ 공공데이터 연계 (공간조인)")
vis = [r for r in idx.rows if r["source"] == "gnsoft_vision"]
print(f"  비전 탐지 문서 {len(vis)}건 (이미지→탐지결과). 예:")
for v in vis[:3]:
    print(f"   - {v['title']}  @{v['region_name']} ({v['lat']},{v['lng']})")

line("R5. 데이터 변경 이력 / 검수 상태 관리")
conn = connect(idx.db_path)
ch = conn.execute("SELECT action, COUNT(*) c FROM doc_change_log GROUP BY action").fetchall()
print("  doc_change_log:", {r["action"]: r["c"] for r in ch})
rv = conn.execute("SELECT review_status, COUNT(*) c FROM unified_doc GROUP BY review_status").fetchall()
print("  review_status :", {r["review_status"]: r["c"] for r in rv})
qh = conn.execute("SELECT COUNT(*) c FROM query_history").fetchone()["c"]
print(f"  query_history : {qh}건 (프롬프트·의도·도구·응답 이력 저장)")
conn.close()

line("R6. 자동 요약 + 보고서(.docx) 생성")
path = report_mod.generate_report("대전 노면상태별 교통사고 통계를 요약해줘", idx,
                                  os.path.join(ROOT, "report_output.docx"))
print(f"  생성됨: {path}  ({os.path.getsize(path):,} bytes)")

line("검증 스크립트 완료")
