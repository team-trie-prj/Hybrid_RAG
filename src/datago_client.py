"""공공데이터포털(data.go.kr) 연동 클라이언트.

────────────────────────────────────────────────────────────────────────
[인증키 발급 방법]  ※ API가 필요한 경우
1. https://www.data.go.kr 회원가입 / 로그인
2. 원하는 데이터셋 페이지 접속 (예: 노면상태별 교통사고 통계 = dataset 15130420)
3. "활용신청" 클릭 → 활용목적 입력 → 신청 (대부분 자동승인, 즉시~1시간)
4. 마이페이지 > 데이터활용 > 인증키(일반 인증키, serviceKey) 확인
5. 환경변수로 등록:  $env:DATAGO_SERVICE_KEY = "발급받은키"
   (Decoding 키를 쓰면 requests가 자동 인코딩, Encoding 키면 그대로 사용)

[파일 데이터 vs OpenAPI]
- 위 4개 데모 데이터셋 중 다수는 "파일데이터(CSV)"라 로그인 후 수동 다운로드 →
  data/raw/ 에 넣고 etl.py 로 정규화하는 것이 가장 간단하다.
- "오픈API"로 제공되는 데이터셋은 아래 fetch_openapi()로 직접 수집할 수 있다.
────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import os
from typing import Any, Optional

SERVICE_KEY_ENV = "DATAGO_SERVICE_KEY"


def has_key() -> bool:
    return bool(os.getenv(SERVICE_KEY_ENV))


def fetch_openapi(endpoint: str, params: Optional[dict] = None,
                  page: int = 1, rows: int = 100, data_type: str = "JSON") -> dict[str, Any]:
    """data.go.kr 오픈API 1페이지 호출 → dict 반환.

    endpoint 예: "https://apis.data.go.kr/B552061/...."  (각 데이터셋 페이지의 요청주소)
    serviceKey는 환경변수에서 자동 주입한다.
    """
    import requests

    key = os.getenv(SERVICE_KEY_ENV)
    if not key:
        raise RuntimeError(f"{SERVICE_KEY_ENV} 환경변수가 없습니다. 모듈 상단 가이드 참조.")

    q = {"serviceKey": key, "pageNo": page, "numOfRows": rows,
         "type": data_type, "dataType": data_type, **(params or {})}
    resp = requests.get(endpoint, params=q, timeout=20)
    resp.raise_for_status()
    ctype = resp.headers.get("Content-Type", "")
    if "json" in ctype.lower() or data_type.upper() == "JSON":
        try:
            return resp.json()
        except ValueError:
            pass
    # XML 폴백
    import xml.etree.ElementTree as ET
    root = ET.fromstring(resp.text)
    return {"xml_items": [{c.tag: c.text for c in item} for item in root.iter("item")]}


def fetch_all(endpoint: str, params: Optional[dict] = None,
              rows: int = 100, max_pages: int = 50, items_path: tuple = ()) -> list[dict]:
    """페이지네이션 순회 수집. items_path로 응답 내 item 리스트 위치를 지정."""
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        data = fetch_openapi(endpoint, params, page=page, rows=rows)
        node: Any = data
        for k in items_path:
            node = node.get(k, {}) if isinstance(node, dict) else {}
        items = node if isinstance(node, list) else data.get("xml_items", [])
        if not items:
            break
        out += items
        if len(items) < rows:
            break
    return out


if __name__ == "__main__":
    if has_key():
        print(f"인증키 감지됨. fetch_openapi(endpoint, params)로 수집 가능.")
    else:
        print(f"인증키 없음. {SERVICE_KEY_ENV} 설정 후 사용하세요. (모듈 상단 가이드 참조)")
