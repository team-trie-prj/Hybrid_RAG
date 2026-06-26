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
SEED_OUT = os.path.join(ROOT, "data", "datasets", "api_catalog_seed.json")
SERVICE_KEY_ENV = "DATAGO_SERVICE_KEY"

# ── 메타 API 장애 대비 '검증된 실데이터 시드' (웹 확인된 실제 data.go.kr 데이터셋) ──
# (dataset_id, 제목, 기관, 내부도메인, 유형[api|standard|file])
SEED_DATASETS: list[tuple] = [
    # 대기환경/기상
    ("15073861", "에어코리아 대기오염정보", "한국환경공단", "대기환경", "api"),
    ("15073885", "에어코리아 미세먼지 경보 발령 현황", "한국환경공단", "대기환경", "api"),
    ("15112307", "에어코리아 고농도 초미세먼지 예보", "한국환경공단", "대기환경", "api"),
    ("15075624", "에어코리아 사용자 지원(측정소 부가)", "한국환경공단", "대기환경", "api"),
    ("15156708", "에어코리아 측정소 정보 조회", "한국환경공단", "대기환경", "api"),
    ("15104339", "대전교통공사 초미세먼지측정정보", "대전교통공사", "대기환경", "api"),
    ("15057173", "부산광역시 대기질 정보 조회", "부산광역시", "대기환경", "api"),
    ("15084084", "기상청 단기예보 조회서비스", "기상청", "대기환경", "api"),
    ("15059468", "기상청 중기예보 조회서비스", "기상청", "대기환경", "api"),
    ("15081073", "국립환경과학원 수질 DB", "국립환경과학원", "대기환경", "api"),
    ("15056633", "국립환경과학원 생활계 물사용량 정보", "국립환경과학원", "대기환경", "api"),
    ("15106003", "한국환경공단 폐기물통계정보", "한국환경공단", "대기환경", "api"),
    ("15139225", "전국폐수처리업체표준데이터", "환경부", "대기환경", "standard"),
    ("15134417", "한국수자원공사 지하수 오염측정망 수질정보", "한국수자원공사", "대기환경", "api"),
    # 교통안전
    ("15057467", "도로교통공단 지자체별 교통사고 다발지역", "도로교통공단", "교통안전", "api"),
    ("15057393", "경기도 사고다발지 현황", "경기도", "교통안전", "api"),
    ("15076684", "한국도로공사 실시간 소통 데이터", "한국도로공사", "교통안전", "api"),
    ("15076696", "한국도로공사 현재 교통예보 현황", "한국도로공사", "교통안전", "api"),
    ("15076721", "한국도로공사 톨게이트 입/출구 교통량", "한국도로공사", "교통안전", "api"),
    ("15076872", "한국도로공사 실시간 영업소별 교통량", "한국도로공사", "교통안전", "api"),
    ("15076822", "한국도로공사 실시간 전국 교통량", "한국도로공사", "교통안전", "api"),
    ("15150101", "한국교통안전공단 주차장실시간정보", "한국교통안전공단", "교통안전", "file"),
    ("15099883", "한국교통안전공단 주차정보 제공 API", "한국교통안전공단", "교통안전", "api"),
    ("15098534", "국토교통부(TAGO) 버스정류소정보", "국토교통부", "교통안전", "api"),
    ("15012896", "전국주차장정보표준데이터", "행정안전부", "교통안전", "standard"),
    ("15058320", "대전광역시 노선정보조회 서비스", "대전광역시", "교통안전", "api"),
    # 도로시설
    ("15142616", "한국도로공사 포트홀 및 피해배상 현황", "한국도로공사", "도로시설", "file"),
    ("15050223", "한국도로공사 포장 보수현황", "한국도로공사", "도로시설", "file"),
    ("15097977", "전북특별자치도 포트홀 보수 데이터", "전북특별자치도", "도로시설", "api"),
    ("15076874", "한국도로공사 고속도로 공사현황", "한국도로공사", "도로시설", "api"),
    ("15076644", "한국도로공사 휴게소 편의시설 현황", "한국도로공사", "도로시설", "api"),
    ("15076641", "한국도로공사 노선별 휴게시설 현황", "한국도로공사", "도로시설", "api"),
    ("15062048", "한국도로공사 공간정보 노선기본", "한국도로공사", "도로시설", "api"),
    ("15085543", "한국도로공사 휴게소 전기차/수소차 충전소 현황", "한국도로공사", "도로시설", "file"),
    ("15134735", "국토교통부 건축HUB 건축물대장정보", "국토교통부", "도로시설", "api"),
    # 재난안전
    ("15077644", "소방청 화재정보서비스", "소방청", "재난안전", "api"),
    ("15099423", "소방청 구급정보서비스", "소방청", "재난안전", "api"),
    ("15155779", "소방청 특정소방대상물 소방시설정보서비스", "소방청", "재난안전", "api"),
    ("15134001", "행정안전부 긴급재난문자", "행정안전부", "재난안전", "api"),
    ("15139158", "소방청 119구급서비스 통계연보", "소방청", "재난안전", "file"),
    ("15128648", "국민권익위 민원빅데이터 분석정보 API", "국민권익위원회", "재난안전", "api"),
    ("15025425", "소방청 헬기 구조 현황", "소방청", "재난안전", "file"),
    ("15080972", "소방청 세종시 화재 종별 신고", "소방청", "재난안전", "file"),
    ("15080046", "소방청 본부별 구급활동정보", "소방청", "재난안전", "file"),
    ("15149423", "한국환경공단 유독물GHS 정보 조회", "한국환경공단", "재난안전", "api"),
    ("15149420", "한국환경공단 화학물질 정보 조회", "한국환경공단", "재난안전", "api"),
    # 인구
    ("15108065", "행안부 행정동별 주민등록 인구·세대현황", "행정안전부", "인구", "api"),
    ("15108072", "행안부 행정동별 성/연령별 주민등록 인구수", "행정안전부", "인구", "api"),
    ("15108092", "행안부 도로명별 주민등록 인구·세대현황", "행정안전부", "인구", "api"),
    ("15107303", "행안부 통계연보 지역별 주민등록인구", "행정안전부", "인구", "api"),
    ("15108093", "행안부 지역별 인구이동 현황", "행정안전부", "인구", "api"),
    # 생활안전
    ("15101889", "행안부 생활안전지도 치안안전시설", "행정안전부", "생활안전", "api"),
    ("3068943", "국토교통부 교통CCTV", "국토교통부", "생활안전", "api"),
    ("15012891", "전국어린이보호구역표준데이터", "행정안전부", "생활안전", "standard"),
    ("15056759", "어린이보호구역(위치·CCTV)", "행정안전부", "생활안전", "api"),
    ("15075538", "행안부 CCTV정보", "행정안전부", "생활안전", "file"),
    ("15010990", "전주시 어린이보호구역", "전주시", "생활안전", "api"),
    ("15034535", "전국여성안심지킴이집표준데이터", "행정안전부", "생활안전", "standard"),
    ("15057670", "경찰청 습득물정보 조회 서비스", "경찰청", "생활안전", "api"),
    ("15000651", "경찰청 공통코드조회 서비스", "경찰청", "생활안전", "api"),
    ("15146211", "서울특별시 실시간 도시데이터", "서울특별시", "생활안전", "api"),
    # 생활복지/의료
    ("15075537", "행안부 무료와이파이정보", "행정안전부", "생활복지", "file"),
    ("15056929", "국토교통부 노인복지시설", "국토교통부", "생활복지", "api"),
    ("15000736", "국립중앙의료원 전국 병·의원 찾기", "국립중앙의료원", "생활복지", "api"),
    ("15000576", "국립중앙의료원 전국 약국 정보", "국립중앙의료원", "생활복지", "api"),
    ("15011425", "경기도 공중화장실 현황", "경기도", "생활복지", "api"),
    ("15077995", "대전광역시 서구 공중화장실", "대전광역시서구", "생활복지", "api"),
    ("15001699", "건강보험심사평가원 의료기관별상세정보서비스", "건강보험심사평가원", "생활복지", "api"),
    ("15001698", "건강보험심사평가원 병원정보서비스", "건강보험심사평가원", "생활복지", "api"),
    ("15087442", "질병관리청 국가건강정보포털", "질병관리청", "생활복지", "api"),
    ("15063908", "식약처 묶음의약품정보서비스", "식품의약품안전처", "생활복지", "api"),
    ("15047819", "건강보험심사평가원 의약품사용정보조회서비스", "건강보험심사평가원", "생활복지", "api"),
    ("15013109", "전국도서관표준데이터", "행정안전부", "생활복지", "standard"),
    ("15068423", "식약처 연구관리 기술 분류 정보조회", "식품의약품안전처", "생활복지", "api"),
    ("15080330", "식약처 연구관리 기관 조회서비스", "식품의약품안전처", "생활복지", "api"),
    ("15013115", "전국전기차충전소표준데이터", "환경부", "생활복지", "standard"),
    ("15124909", "전국 관광지 주변 전기차충전소 정보", "한국문화정보원", "생활복지", "api"),
    ("15147132", "한국전력공사 전기차 충전소 운영 정보", "한국전력공사", "생활복지", "api"),
    ("15097923", "한국에너지공단 전기차 급속충전기 충전 정보", "한국에너지공단", "생활복지", "api"),
    ("15134145", "한국수자원공사 상수도 정수 수질검사 정보", "한국수자원공사", "생활복지", "api"),
    # 부동산/국토
    ("15126469", "국토교통부 아파트 매매 실거래가 자료", "국토교통부", "생활복지", "api"),
    ("15126474", "국토교통부 아파트 전월세 실거래가 자료", "국토교통부", "생활복지", "api"),
    ("15126471", "국토교통부 아파트 분양권전매 실거래가 자료", "국토교통부", "생활복지", "api"),
    ("15126463", "국토교통부 상업업무용 부동산 매매 실거래가", "국토교통부", "생활복지", "api"),
    ("15134761", "한국부동산원 부동산통계 조회 서비스", "한국부동산원", "생활복지", "api"),
]

_TYPE_SUFFIX = {"api": "openapi.do", "standard": "standard.do", "file": "fileData.do"}


def seed_catalog() -> list[dict]:
    """검증된 실데이터 시드를 카탈로그 항목 형식으로 확장."""
    out = []
    for ds_id, title, org, domain, typ in SEED_DATASETS:
        url = f"https://www.data.go.kr/data/{ds_id}/{_TYPE_SUFFIX.get(typ, 'openapi.do')}"
        out.append({
            "dataset_id": ds_id, "title": title, "source": "data.go.kr",
            "org": org, "domain": domain, "doc_type": "open_api", "data_type": typ,
            "provenance_url": url,
            "api": {"endpoint": "", "params": {},
                    "items_path": ["response", "body", "items", "item"]},
        })
    return out

# 메타 오픈API: 공공데이터포털목록조회서비스(getPortalOpenApiList).
# data.go.kr는 구 게이트웨이(openapi.data.go.kr)에서 신 게이트웨이(apis.data.go.kr)로
# 이전 중이라 호스트별로 가용성이 다르다. 순서대로 시도한다. 환경변수로 덮어쓰기 가능.
_PATH = "openapi/service/rest/PortalOpenApiService/getPortalOpenApiList"
PORTAL_ENDPOINTS = [
    os.getenv("DATAGO_PORTAL_ENDPOINT") or f"https://apis.data.go.kr/{_PATH}",
    f"http://apis.data.go.kr/{_PATH}",
    f"http://openapi.data.go.kr/{_PATH}",
]

# data.go.kr 인증 실패(키 미등록/미승인) 시 응답 본문에 나타나는 표식
AUTH_ERROR_MARKS = ("SERVICE_KEY_IS_NOT_REGISTERED", "<returnReasonCode>30",
                    "SERVICE ERROR", "등록되지 않은 서비스")

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


def _resolve_endpoint(key: str):
    """가용 호스트를 탐색해 동작하는 엔드포인트를 고른다. (endpoint, 진단메시지)."""
    import time
    import requests
    last = ""
    for url in PORTAL_ENDPOINTS:
        for attempt in range(2):
            try:
                r = requests.get(url, params={"serviceKey": key, "numOfRows": 1,
                                              "pageNo": 1, "type": "json"}, timeout=25)
                body = (r.text or "")[:300]
                if any(m in body for m in AUTH_ERROR_MARKS):
                    return None, (f"인증키가 이 메타 API(15059351)에 미등록/미승인입니다. "
                                  f"data.go.kr에서 '공공데이터포털목록조회서비스' 활용신청 필요.\n   응답: {body[:120]}")
                if r.status_code == 200 and _items_from_response(r.text):
                    return url, f"OK ({url})"
                last = f"HTTP {r.status_code} @ {url}"
                if r.status_code in (500, 502, 503):  # 서버 일시 장애 → 다음 호스트/재시도
                    time.sleep(1.5)
                    continue
            except Exception as e:
                last = f"{type(e).__name__} @ {url}"
                time.sleep(1.0)
    return None, f"가용 호스트 없음(서버 장애 추정). 마지막: {last}"


def fetch_catalog(target: int = 400, rows: int = 100, max_pages: int = 60) -> list[dict]:
    import requests

    key = os.getenv(SERVICE_KEY_ENV)
    if not key:
        raise RuntimeError(f"{SERVICE_KEY_ENV} 환경변수가 없습니다. .env 에 키를 넣고 run.ps1 사용.")

    endpoint, diag = _resolve_endpoint(key)
    print(f"  엔드포인트 탐색: {diag}")
    if not endpoint:
        raise RuntimeError(diag)

    collected: list[dict] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        params = {"serviceKey": key, "numOfRows": rows, "pageNo": page, "type": "json"}
        resp = requests.get(endpoint, params=params, timeout=30)
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


def _write_seed() -> list[dict]:
    """메타 API 대체: 검증된 실데이터 시드를 api_catalog_seed.json 으로 저장."""
    seed = seed_catalog()
    os.makedirs(os.path.dirname(SEED_OUT), exist_ok=True)
    with open(SEED_OUT, "w", encoding="utf-8") as f:
        json.dump(seed, f, ensure_ascii=False, indent=2)
    return seed


def main(argv: list[str]) -> None:
    target = int(argv[0]) if argv and argv[0].isdigit() else 400
    print(f"공공데이터포털 오픈API 카탈로그 수집 시작 (목표 {target}종)")
    print(f"  메타 API 후보: {PORTAL_ENDPOINTS}")
    from collections import Counter

    try:
        catalog = fetch_catalog(target=target)
    except Exception as e:
        # 메타 API 장애(현재 data.go.kr 서버측 5xx) → 검증된 실데이터 시드로 대체
        print(f"\n⚠️ 메타 API 수집 불가: {type(e).__name__}: {e}")
        seed = _write_seed()
        dist = Counter(c["domain"] for c in seed)
        print(f"\n→ 대체: 검증된 실데이터 시드 카탈로그 {len(seed)}종 저장 → {SEED_OUT}")
        print("  도메인 분포:", dict(dist))
        print(f"  (메타 API 복구 시 'build_api_catalog.py {target}' 재실행하면 {target}종 자동 확장)")
        return

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)
    dist = Counter(c["domain"] for c in catalog)
    print(f"\n✅ 수집 완료: {len(catalog)}종 → {OUT}")
    print("  도메인 분포:", dict(dist))
    print(f"  목표({target}종) 충족: {'예' if len(catalog) >= target else '아니오'}")


if __name__ == "__main__":
    main(sys.argv[1:])
