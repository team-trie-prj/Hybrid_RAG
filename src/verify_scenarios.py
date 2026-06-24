# -*- coding: utf-8 -*-
"""제안서 명시 데모 시나리오를 Gemini 에이전트로 실제 실행."""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm
from agent import ask
from retrieve import Index

print("Gemini 사용 가능:", llm.gemini_available(), "| 모델:", llm.MODEL)
idx = Index()
SCENARIOS = [
    "대전 유성구 포트홀 영역을 찾아줘",
    "공공데이터포털 기반으로 대전 화재 통계를 보여줘",
    "업무 절차를 자동으로 추천해줘: 대전 유성구에서 포트홀이 탐지되면 어떻게 대응해야 해?",
]
for i, q in enumerate(SCENARIOS, 1):
    print(f"\n{'='*70}\n[시나리오 {i}] {q}\n{'='*70}")
    print(ask(q, idx))
