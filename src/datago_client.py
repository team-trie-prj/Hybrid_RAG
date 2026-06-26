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


AIRKOREA_ENDPOINT = ("http://apis.data.go.kr/B552584/ArpltnInforInqireSvc/"
                     "getCtprvnRltmMesureDnsty")


def fetch_airkorea_realtime(sido: str = "대전", rows: int = 50) -> dict[str, Any]:
    """에어코리아 대기오염정보(15073861) 시도별 실시간 측정정보 라이브 조회.

    FR-PUB-001/002 라이브 연동. graceful: 장애/미인증 시 ok=False + user_message.
    반환 ok=True 시 data={"sido","items":[{station,pm10,pm25,dataTime}...]}.
    """
    safe = fetch_openapi_safe(
        AIRKOREA_ENDPOINT,
        {"sidoName": sido, "returnType": "json", "numOfRows": rows, "pageNo": 1, "ver": "1.3"},
    )
    if not safe["ok"]:
        return safe
    body = (safe["data"].get("response", {}) or {}).get("body", {}) or {}
    items = body.get("items", []) or []
    out = [{"station": it.get("stationName"), "pm10": it.get("pm10Value"),
            "pm25": it.get("pm25Value"), "dataTime": it.get("dataTime")} for it in items]
    return {"ok": True, "data": {"sido": sido, "total": body.get("totalCount"), "items": out}}


def fetch_openapi_safe(endpoint: str, params: Optional[dict] = None,
                       page: int = 1, rows: int = 100, data_type: str = "JSON"
                       ) -> dict[str, Any]:
    """fetch_openapi의 graceful 래퍼 (FR-PUB-006 / AT-PUB-05).

    외부 API 장애(미인증/네트워크/타임아웃/HTTP 오류)에도 예외를 전파하지 않고
    {ok, data} 또는 {ok:False, error, user_message}를 반환한다.
    호출부는 ok=False 시 사용자 친화적 안내(user_message)를 표출하면 된다.
    """
    if not has_key():
        return {"ok": False, "error": f"missing {SERVICE_KEY_ENV}",
                "user_message": "공공데이터 API 인증키가 설정되지 않아 실시간 조회를 건너뜁니다. "
                                "적재된 공공데이터로 대체 응답합니다."}
    try:
        data = fetch_openapi(endpoint, params, page=page, rows=rows, data_type=data_type)
        return {"ok": True, "data": data}
    except Exception as e:  # 네트워크/HTTP/파싱 등 모든 외부 장애 흡수
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "user_message": "공공데이터포털을 일시적으로 조회할 수 없습니다. "
                                "잠시 후 다시 시도해 주세요. (적재된 데이터로 대체 가능)"}


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
