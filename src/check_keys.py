# -*- coding: utf-8 -*-
"""Gemini/Voyage 키 연동 진단: 환경변수 인식 → SDK 설치 → 실제 API 호출까지."""
from __future__ import annotations
import os, sys


def mask(v: str | None) -> str:
    if not v:
        return "(없음)"
    return f"{v[:4]}…{v[-4:]} (len={len(v)})"


print("=== 1) 환경변수 인식 (이 파이썬 프로세스 기준) ===")
gem = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
voy = os.getenv("VOYAGE_API_KEY")
print(f"  GEMINI_API_KEY : {mask(os.getenv('GEMINI_API_KEY'))}")
print(f"  GOOGLE_API_KEY : {mask(os.getenv('GOOGLE_API_KEY'))}")
print(f"  VOYAGE_API_KEY : {mask(voy)}")
print(f"  GEMINI_MODEL   : {os.getenv('GEMINI_MODEL') or '(기본 gemini-3.5-flash)'}")

print("\n=== 2) Voyage 임베딩 실제 호출 ===")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from embeddings import Embeddings
    emb = Embeddings()
    print(f"  Embeddings.provider = {emb.provider}")
    if emb.provider == "voyage-3":
        vecs = emb.embed(["대전 유성구 포트홀 현황"], input_type="document")
        print(f"  ✅ Voyage 호출 성공 — 차원 {len(vecs[0])} (voyage-3=1024 예상)")
    elif voy:
        # 키는 있는데 provider가 local로 폴백 → 원인 직접 진단
        print("  ⚠️ 키는 감지됐으나 provider가 local-hash로 폴백됨. 원인 진단:")
        try:
            import voyageai
            voyageai.Client().embed(["테스트"], model="voyage-3", input_type="document")
            print("     (재시도는 성공 — embeddings.py 초기화 시점 문제일 수 있음)")
        except Exception as e:
            print(f"     ❌ {type(e).__name__}: {e}")
    else:
        print("  ⚠️ VOYAGE_API_KEY 미감지 → 로컬 해시 임베딩 사용 중")
except Exception as e:
    print(f"  ❌ {type(e).__name__}: {e}")

print("\n=== 3) Gemini 실제 호출 ===")
if not gem:
    print("  ⚠️ GEMINI_API_KEY/GOOGLE_API_KEY 미감지 → 오프라인 규칙 라우터 사용 중")
else:
    try:
        from google import genai
        model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
        client = genai.Client()
        resp = client.models.generate_content(model=model, contents="한 단어로만 답해: 안녕?")
        txt = (getattr(resp, "text", None) or "").strip()
        print(f"  ✅ Gemini 호출 성공 (model={model}) — 응답: {txt[:60]!r}")
    except Exception as e:
        print(f"  ❌ {type(e).__name__}: {e}")
        print("     → 모델 ID가 틀리면 GEMINI_MODEL 환경변수로 교체 가능.")
