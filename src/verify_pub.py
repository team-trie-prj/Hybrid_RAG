# -*- coding: utf-8 -*-
"""FR-PUB 검증: 공공데이터포털 연동·인증 + 오픈API 카탈로그 400종.

1) FR-PUB-001 연동·인증: 메타 오픈API(getPortalOpenApiList) 실 호출로 인증 확인.
2) '오픈API 데이터셋 400종 등록': api_catalog.json 항목 수 ≥ 400 확인.
3) FR-PUB-006 graceful: 장애 시 예외 비전파 확인.

키(DATAGO_SERVICE_KEY)가 없으면 1)은 SKIP하고 안내한다.
실행:  python verify_pub.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import datago_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(ROOT, "data", "datasets", "api_catalog.json")


def line(t):
    print("\n" + "─" * 68 + f"\n▶ {t}\n" + "─" * 68)


# 1) 연동·인증 (라이브)
line("FR-PUB-001 공공데이터포털 연동·인증 (메타 오픈API 실 호출)")
if not datago_client.has_key():
    print("  ⚠️ SKIP — DATAGO_SERVICE_KEY 미설정.")
    print("     .env 에 DATAGO_SERVICE_KEY=발급키 추가 후 run.ps1 로 재실행하면 라이브 검증됩니다.")
else:
    import build_api_catalog as bac
    try:
        import requests
        params = {"serviceKey": os.getenv("DATAGO_SERVICE_KEY"), "numOfRows": 5, "pageNo": 1}
        r = requests.get(bac.PORTAL_ENDPOINT, params=params, timeout=30)
        items = bac._items_from_response(r.text)
        ok = r.status_code == 200 and len(items) > 0
        print(f"  HTTP {r.status_code}, 파싱 item {len(items)}건 → {'PASS' if ok else 'FAIL'}")
        if items:
            print(f"  예시: {bac._first(items[0], 'title','listTitle','dataName','데이터명')[:40]}")
    except Exception as e:
        print(f"  ❌ FAIL — {type(e).__name__}: {e}")

# 2) 오픈API 카탈로그 400종
line("오픈API 데이터셋 400종 등록 (api_catalog.json)")
if os.path.exists(CATALOG):
    with open(CATALOG, encoding="utf-8") as f:
        cat = json.load(f)
    from collections import Counter
    dist = Counter(c.get("domain", "기타") for c in cat)
    print(f"  카탈로그 등록 수: {len(cat)}종 → {'PASS' if len(cat) >= 400 else 'FAIL (목표 400)'}")
    print(f"  도메인 분포: {dict(dist)}")
else:
    print(f"  ⚠️ 카탈로그 미생성 — 키 설정 후 'python build_api_catalog.py' 실행 필요.")

# 3) graceful 처리
line("FR-PUB-006 / AT-PUB-05 외부 API 오류 graceful 처리")
r = datago_client.fetch_openapi_safe("https://invalid.invalid.example/none", {"x": 1})
print(f"  무인증/장애 호출 → ok={r['ok']}, 안내='{r.get('user_message','')[:36]}…' "
      f"→ {'PASS' if r['ok'] is False and 'user_message' in r else 'FAIL'}")
