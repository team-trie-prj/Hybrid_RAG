# -*- coding: utf-8 -*-
"""FR-PUB 검증: 공공데이터포털 연동·인증(라이브) + 오픈API 카탈로그.

1) FR-PUB-001/002 연동·인증·조회: 에어코리아 대기오염정보(15073861) 실 호출·파싱.
2) '오픈API 데이터셋 400종 등록': api_catalog.json / api_catalog_seed.json 항목 수.
3) FR-PUB-006 graceful: 장애 시 예외 비전파 확인.

키(DATAGO_SERVICE_KEY) 없으면 1)은 SKIP. 실행:  python verify_pub.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import datago_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(ROOT, "data", "datasets", "api_catalog.json")
SEED = os.path.join(ROOT, "data", "datasets", "api_catalog_seed.json")


def line(t):
    print("\n" + "─" * 68 + f"\n▶ {t}\n" + "─" * 68)


# 1) 연동·인증·조회 (라이브) — 에어코리아 15073861
line("FR-PUB-001/002 공공데이터포털 연동·인증·조회 (라이브: 에어코리아 15073861)")
if not datago_client.has_key():
    print("  ⚠️ SKIP — DATAGO_SERVICE_KEY 미설정. .env 에 키 추가 후 run.ps1 로 재실행.")
else:
    res = datago_client.fetch_airkorea_realtime("대전", rows=5)
    if res["ok"]:
        d = res["data"]
        print(f"  ✅ PASS — HTTP 200, 시도={d['sido']}, totalCount={d['total']}, 파싱 {len(d['items'])}건")
        for it in d["items"][:3]:
            print(f"     - {it['station']}  PM10={it['pm10']}  PM2.5={it['pm25']}  ({it['dataTime']})")
    else:
        print(f"  ❌ FAIL — {res.get('error')}")
        print(f"     안내: {res.get('user_message')}")
        print("     (해당 데이터셋 활용신청/승인 여부 확인 필요)")

# 2) 오픈API 카탈로그 등록 현황
line("오픈API 데이터셋 카탈로그 등록 현황")
path = CATALOG if os.path.exists(CATALOG) else (SEED if os.path.exists(SEED) else None)
if path:
    with open(path, encoding="utf-8") as f:
        cat = json.load(f)
    from collections import Counter
    dist = Counter(c.get("domain", "기타") for c in cat)
    src = "메타API 수집본" if path == CATALOG else "검증된 실데이터 시드(메타API 대체)"
    print(f"  카탈로그({src}): {len(cat)}종  → 목표 400 {'충족' if len(cat) >= 400 else '미충족'}")
    print(f"  도메인 분포: {dict(dist)}")
else:
    print("  ⚠️ 카탈로그 미생성 — build_api_catalog.py 실행 또는 시드 생성 필요.")

# 3) graceful 처리
line("FR-PUB-006 / AT-PUB-05 외부 API 오류 graceful 처리")
r = datago_client.fetch_openapi_safe("https://invalid.invalid.example/none", {"x": 1})
print(f"  장애 호출 → ok={r['ok']}, 안내='{r.get('user_message','')[:36]}…' "
      f"→ {'PASS' if r['ok'] is False and 'user_message' in r else 'FAIL'}")
