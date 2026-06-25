# -*- coding: utf-8 -*-
"""공공데이터포털 오픈API 카탈로그 빌더 (FR-PUB '오픈API 데이터셋 400종 등록').

data.go.kr 메타 오픈API '공공데이터포털목록조회서비스'(dataset 15059351)를
인증키로 호출해 실제 등록 오픈API 목록을 수집하고, data/datasets/api_catalog.json
으로 저장한다. 이렇게 만들어진 카탈로그는 load_datago.py가 인증키로 호출 가능한
'연동 대상' 레지스트리가 된다.

사전 준비:  $env:DATAGO_SERVICE_KEY = "발급키"   (.env 에 넣고 run.ps1 사용 가능)
실행:       python build_api_catalog.py [목표개수=400]
출력:       data/datasets/api_catalog.json  (+ 콘솔 요약)
"""
from __future__ import annotations

import json
import os
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "datasets", "api_catalog.json")
SERVICE_KEY_ENV = "DATAGO_SERVICE_KEY"

# 메타 오픈API: 공공데이터포털목록조회서비스(getPortalOpenApiList). 환경변수로 덮어쓰기 가능.
PORTAL_ENDPOINT = os.getenv(
    "DATAGO_PORTAL_ENDPOINT",
    "http://openapi.data.go.kr/openapi/service/rest/PortalOpenApiService/getPortalOpenApiList",
)

# 카탈로그 항목 → 내부 도메인 추정용 키워드(공공데이터 분류명/제목 기반)
DOMAIN_HINT = {
    "교통안전": ["교통", "사고", "차량", "운전", "도로교통"],
    "도로시설": ["도로", "포트홀", "포장", "터널", "교량", "노선"],
    "대기환경": ["대기", "미세먼지", "오존", "환경", "수질", "기상"],
    "재난안전": ["화재", "소방", "재난", "안전", "재해", "구조"],
    "인구": ["인구", "주민", "세대", "출생", "고령"],
    "생활안전": ["cctv", "방범", "치안", "범죄"],
    "생활복지": ["와이파이", "복지", "보육", "의료", "보건"],
}


def _infer_domain(text: str) -> str:
    t = (text or "").lower()
    for dom, kws in DOMAIN_HINT.items():
        if any(k.lower() in t for k in kws):
            return dom
    return "기타"


def _items_from_response(text: str) -> list[dict]:
    """JSON 또는 XML 응답에서 item 리스트를 추출(태그→텍스트 dict)."""
    text = text.strip()
    if text.startswith("{"):
        data = json.loads(text)
        node = data
        for key in ("response", "body", "items", "item"):
            if isinstance(node, dict) and key in node:
                node = node[key]
        if isinstance(node, dict):
            node = node.get("item", node)
        return node if isinstance(node, list) else [node] if node else []
    # XML
    root = ET.fromstring(text)
    out = []
    for item in root.iter("item"):
        out.append({c.tag: (c.text or "").strip() for c in item})
    return out


def _first(d: dict, *keys: str, default: str = "") -> str:
    for k in keys:
        if d.get(k):
            return str(d[k])
    return default


def fetch_catalog(target: int = 400, rows: int = 100, max_pages: int = 60) -> list[dict]:
    import requests

    key = os.getenv(SERVICE_KEY_ENV)
    if not key:
        raise RuntimeError(f"{SERVICE_KEY_ENV} 환경변수가 없습니다. .env 에 키를 넣고 run.ps1 사용.")

    collected: list[dict] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        params = {"serviceKey": key, "numOfRows": rows, "pageNo": page}
        resp = requests.get(PORTAL_ENDPOINT, params=params, timeout=30)
        resp.raise_for_status()
        items = _items_from_response(resp.text)
        if not items:
            break
        for i, it in enumerate(items):
            # 메타 응답의 필드명은 데이터셋마다 다를 수 있어 여러 후보를 시도한다.
            title = _first(it, "title", "listTitle", "openApiTitle", "dataName", "데이터명")
            org = _first(it, "orgNm", "organization", "기관명", "providerNm")
            category = _first(it, "category", "classfcNm", "분류체계", "listKorNm")
            link = _first(it, "link", "url", "listUrl", "detailUrl")
            ds_id = _first(it, "publicDataPk", "listId", "dataId", "id") or f"portal-{page}-{i}"
            if ds_id in seen:
                continue
            seen.add(ds_id)
            collected.append({
                "dataset_id": ds_id,
                "title": title or "(제목없음)",
                "source": "data.go.kr",
                "domain": _infer_domain(f"{title} {category}"),
                "doc_type": "open_api",
                "org": org,
                "category": category,
                "provenance_url": link or f"https://www.data.go.kr/data/{ds_id}/openapi.do",
                "api": {"endpoint": link or "", "params": {}, "items_path": ["response", "body", "items", "item"]},
                "raw": it,
            })
        print(f"  page {page}: 누적 {len(collected)}건")
        if len(collected) >= target:
            break
    return collected


def main(argv: list[str]) -> None:
    target = int(argv[0]) if argv and argv[0].isdigit() else 400
    print(f"공공데이터포털 오픈API 카탈로그 수집 시작 (목표 {target}종)")
    print(f"  메타 API: {PORTAL_ENDPOINT}")
    try:
        catalog = fetch_catalog(target=target)
    except Exception as e:
        print(f"\n❌ 수집 실패: {type(e).__name__}: {e}")
        print("   → 인증키(DATAGO_SERVICE_KEY)와 메타 API 활용신청 상태를 확인하세요.")
        sys.exit(2)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)

    # 도메인 분포 요약
    from collections import Counter
    dist = Counter(c["domain"] for c in catalog)
    print(f"\n✅ 수집 완료: {len(catalog)}종 → {OUT}")
    print("  도메인 분포:", dict(dist))
    print(f"  목표({target}종) 충족: {'예' if len(catalog) >= target else '아니오'}")


if __name__ == "__main__":
    main(sys.argv[1:])
