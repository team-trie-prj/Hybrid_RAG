"""범용 매퍼: 매핑 config(JSON) + 원본 행(dict) → UnifiedDoc.

새 공공데이터셋을 붙일 때 파이썬 코드를 새로 짤 필요 없이
data/datasets/*.json 에 매핑 config 한 개만 추가하면 된다.

config 스키마 (예시는 data/datasets/*.json 참고):
{
  "dataset_id", "source", "domain", "doc_type",
  "title_template", "text_template",   # {컬럼명}, {region}, {period} 치환
  "region_field", "period_field", "lat_field", "lng_field",   # 선택
  "metrics": {"표준지표명": "원본컬럼"},        # 숫자 지표
  "string_metrics": {"표준키": "원본컬럼"},      # 문자 지표(예: 노면상태)
  "tag_fields": ["원본컬럼", ...],
  "id_fields": ["원본컬럼", ...],
  "provenance_url",
  "source_file"  또는  "api": {"endpoint","params","items_path"}
}
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

import geo
import regions


def _num(v: Any) -> float:
    try:
        return float(re.sub(r"[,\s]", "", str(v)))
    except (ValueError, TypeError):
        return 0.0


def _slug(parts: list[str]) -> str:
    s = "-".join(str(p) for p in parts if p)
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", s)[:60] or "row"


def _render(template: str, row: dict, region: str, period: str) -> str:
    ctx = defaultdict(str, {k: ("" if v is None else str(v)) for k, v in row.items()})
    ctx["region"] = region
    ctx["period"] = period
    try:
        return template.format_map(ctx)
    except (KeyError, IndexError, ValueError):
        return template


def build_doc(row: dict, cfg: dict, idx: int) -> dict:
    # 지역 해석: region_field 값 → 코드, 좌표 있으면 대전 자치구 보정
    region_raw = str(row.get(cfg.get("region_field", ""), "")).strip()
    reg = regions.code_for_region_name(region_raw) if region_raw else \
        {"sido_cd": None, "sigungu_cd": None, "region_name": None}

    lat = _num(row[cfg["lat_field"]]) if cfg.get("lat_field") and row.get(cfg["lat_field"]) else None
    lng = _num(row[cfg["lng_field"]]) if cfg.get("lng_field") and row.get(cfg["lng_field"]) else None
    if lat and lng:
        gu = geo.reverse_geocode_gu(lat, lng)
        if gu:
            reg["sigungu_cd"], reg["sido_cd"] = gu, "30"
            reg["region_name"] = regions.region_name("30", gu)

    period_raw = str(row.get(cfg.get("period_field", ""), "")).strip()
    period = period_raw[:4] if period_raw[:4].isdigit() else period_raw  # 날짜→연도
    occurred_at = period_raw if "-" in period_raw else (f"{period}-12-31" if period else "")
    region_name = reg.get("region_name") or region_raw or "전국"

    metrics: dict[str, Any] = {}
    for std, col in cfg.get("metrics", {}).items():
        if col in row:
            metrics[std] = _num(row[col])
    for std, col in cfg.get("string_metrics", {}).items():
        if col in row:
            metrics[std] = str(row[col]).strip()

    tags = [str(row[c]).strip() for c in cfg.get("tag_fields", []) if row.get(c)]
    tags += [cfg.get("domain", ""), cfg.get("doc_type", "")]

    id_parts = [str(row.get(c, "")) for c in cfg.get("id_fields", [])] or [str(idx)]
    doc_id = f"{cfg['source']}-{cfg['dataset_id']}-{_slug(id_parts)}"

    return {
        "doc_id": doc_id,
        "source": cfg["source"],
        "domain": cfg.get("domain", ""),
        "doc_type": cfg["doc_type"],
        "title": _render(cfg.get("title_template", "{region} {period}"), row, region_name, period),
        "text": _render(cfg.get("text_template", ""), row, region_name, period),
        "tags": [t for t in tags if t],
        "geo": {"lat": lat, "lng": lng, "sido_cd": reg.get("sido_cd"),
                "sigungu_cd": reg.get("sigungu_cd"), "region_name": region_name,
                "road_name": row.get(cfg.get("road_field", "")) or None, "road_link_id": None},
        "time": {"occurred_at": occurred_at, "period": period},
        "metrics": metrics,
        "provenance": {"dataset_id": cfg["dataset_id"], "url": cfg.get("provenance_url", "")},
    }
