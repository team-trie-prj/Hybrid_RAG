"""3대 데모 시나리오 일괄 실행."""
from __future__ import annotations

from agent import ask
from retrieve import Index

SCENARIOS = [
    "대전 유성구 포트홀 영역을 찾아줘",
    "전국에서 화재가 가장 많은 지역은?",
    "대전 미세먼지 현황을 알려줘",
    "인구가 많은 지역 순위 보여줘",
    "대전 노면상태별 교통사고 통계를 요약해서 보고서로 만들어줘",
]

if __name__ == "__main__":
    idx = Index()  # 인덱스 1회 로드 후 재사용
    for i, q in enumerate(SCENARIOS, 1):
        print(f"\n{'=' * 70}\n[시나리오 {i}] {q}\n{'=' * 70}")
        print(ask(q, idx))
