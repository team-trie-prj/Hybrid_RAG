"""지역명 ↔ 행정표준코드 resolver (전국 시도 + 대전 자치구).

질의/데이터의 지역명을 코드로 정규화해 메타 필터·조인 키로 쓴다.
실전에서는 행정표준코드 전체 테이블(시군구 250여 개)로 확장하면 된다.
"""
from __future__ import annotations

from typing import Optional

# 시도 2자리 코드
SIDO = {
    "11": ["서울", "서울특별시"], "26": ["부산", "부산광역시"], "27": ["대구", "대구광역시"],
    "28": ["인천", "인천광역시"], "29": ["광주", "광주광역시"], "30": ["대전", "대전광역시"],
    "31": ["울산", "울산광역시"], "36": ["세종", "세종특별자치시"], "41": ["경기", "경기도"],
    "42": ["강원", "강원특별자치도", "강원도"], "43": ["충북", "충청북도"], "44": ["충남", "충청남도"],
    "45": ["전북", "전북특별자치도", "전라북도"], "46": ["전남", "전라남도"],
    "47": ["경북", "경상북도"], "48": ["경남", "경상남도"], "50": ["제주", "제주특별자치도"],
}
# 대전 자치구 (시군구 5자리)
DAEJEON_GU = {
    "30110": "동구", "30140": "중구", "30170": "서구", "30200": "유성구", "30230": "대덕구",
}

_SIDO_NAME = {code: names[-1] for code, names in SIDO.items()}


def sido_name(code: Optional[str]) -> str:
    return _SIDO_NAME.get((code or "")[:2], "미상")


def region_name(sido_cd: Optional[str], sigungu_cd: Optional[str]) -> str:
    gu = DAEJEON_GU.get(sigungu_cd or "")
    sd = sido_name(sido_cd)
    return f"{sd} {gu}" if gu else sd


def resolve(text: str) -> dict[str, Optional[str]]:
    """자유 텍스트에서 지역을 추출 → {sido_cd, sigungu_cd, region_name}."""
    sido_cd = None
    for code, names in SIDO.items():
        if any(n in text for n in names):
            sido_cd = code
            break
    sigungu_cd = None
    for code, gu in DAEJEON_GU.items():
        if gu in text:
            sigungu_cd, sido_cd = code, "30"
            break
    return {"sido_cd": sido_cd, "sigungu_cd": sigungu_cd,
            "region_name": region_name(sido_cd, sigungu_cd) if sido_cd else None}


def code_for_region_name(name: str) -> dict[str, Optional[str]]:
    """데이터 행의 지역명 값(예: '대전광역시', '유성구')을 코드로."""
    return resolve(name or "")
