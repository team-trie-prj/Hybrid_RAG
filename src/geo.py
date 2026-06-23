"""좌표 기반 공간 처리: 역지오코딩(→ 대전 자치구), haversine 거리, 공간 조인.

프로토타입은 자치구 중심좌표 최근접으로 역지오코딩한다.
실전은 PostGIS ST_Contains(행정경계 폴리곤) + ST_DWithin으로 대체된다.
"""
from __future__ import annotations

import math
from typing import Any, Optional

# 대전 자치구 대표 좌표 (행정표준코드: 위도, 경도)
DAEJEON_GU = {
    "30110": ("동구", 36.3115, 127.4549),
    "30140": ("중구", 36.3255, 127.4214),
    "30170": ("서구", 36.3554, 127.3845),
    "30200": ("유성구", 36.3620, 127.3560),
    "30230": ("대덕구", 36.3463, 127.4150),
}
# 대전 대략 경계 (이 박스 밖이면 대전 아님)
DAEJEON_BBOX = (36.18, 127.25, 36.50, 127.56)  # (min_lat, min_lng, max_lat, max_lng)


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """두 좌표 간 거리(미터)."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def in_daejeon(lat: float, lng: float) -> bool:
    mn_la, mn_ln, mx_la, mx_ln = DAEJEON_BBOX
    return mn_la <= lat <= mx_la and mn_ln <= lng <= mx_ln


def reverse_geocode_gu(lat: Optional[float], lng: Optional[float]) -> Optional[str]:
    """좌표 → 대전 자치구 코드(최근접 중심). 대전 밖/좌표없음이면 None."""
    if lat is None or lng is None or not in_daejeon(lat, lng):
        return None
    best, best_d = None, float("inf")
    for code, (_, gla, gln) in DAEJEON_GU.items():
        d = haversine_m(lat, lng, gla, gln)
        if d < best_d:
            best, best_d = code, d
    return best


def gu_name(code: Optional[str]) -> str:
    if code == "30000":
        return "대전광역시(전체)"
    return DAEJEON_GU.get(code, ("미상",))[0] if code else "미상"


def spatial_join(target: dict[str, Any], candidates: list[dict[str, Any]],
                 radius_m: float = 2000.0) -> list[dict[str, Any]]:
    """target(예: 비전 탐지) 좌표 반경 내 candidates(공공데이터)를 거리순 반환."""
    g = target.get("geo", target)
    tlat, tlng = g.get("lat"), g.get("lng")
    if tlat is None or tlng is None:
        return []
    hits = []
    for c in candidates:
        cg = c.get("geo", c)
        clat, clng = cg.get("lat"), cg.get("lng")
        if clat is None or clng is None:
            continue
        dist = haversine_m(tlat, tlng, clat, clng)
        if dist <= radius_m:
            hits.append({**c, "_distance_m": round(dist, 1)})
    return sorted(hits, key=lambda x: x["_distance_m"])
