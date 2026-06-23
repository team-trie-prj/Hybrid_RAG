"""범용 ETL: 데이터셋 레지스트리(config) 기반으로 모든 원본을 UnifiedDoc로 정규화.

새 데이터셋을 붙이려면 data/datasets/registry.json 에 매핑 config 한 개만 추가하면 된다.
(파이썬 코드 수정 불필요 — config 기반 확장)

원본은 source_file(CSV) 또는 api(data.go.kr OpenAPI, load_datago.py 참고)에서 온다.
"""
from __future__ import annotations

import csv
import json
import os
from collections import Counter
from datetime import datetime, timezone

import geo
import mapper

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW = os.path.join(ROOT, "data", "raw")
REGISTRY = os.path.join(ROOT, "data", "datasets", "registry.json")
OUT_JSONL = os.path.join(ROOT, "data", "normalized.jsonl")


def read_csv(path: str) -> list[dict[str, str]]:
    """CSV 읽기 (data.go.kr 파일은 cp949인 경우가 많아 인코딩 폴백)."""
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            with open(path, encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("etl", b"", 0, 1, f"인코딩 판별 실패: {path}")


def load_registry(path: str = REGISTRY) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def map_dataset(cfg: dict, rows: list[dict]) -> list[dict]:
    return [mapper.build_doc(r, cfg, i) for i, r in enumerate(rows)]


def spatial_link_vision(docs: list[dict], radius_m: float = 15000) -> int:
    """비전 탐지 ↔ 반경 내 공공 포트홀 공간조인."""
    potholes = [d for d in docs if d["doc_type"] == "pothole"]
    joined = 0
    for d in docs:
        if d["doc_type"] != "vision_detection":
            continue
        near = geo.spatial_join(d, potholes, radius_m=radius_m)
        if near:
            top = near[0]
            d["metrics"]["linked_public_doc"] = top["doc_id"]
            d["metrics"]["linked_distance_m"] = top["_distance_m"]
            d["text"] += f" 인근 공공 포트홀({top['title']})과 연계됨."
            joined += 1
    return joined


def run_etl(out_path: str = OUT_JSONL) -> list[dict]:
    docs: list[dict] = []
    for cfg in load_registry():
        src = cfg.get("source_file")
        if not src:
            print(f"  (건너뜀: {cfg['dataset_id']} — source_file 없음, API는 load_datago.py)")
            continue
        path = os.path.join(RAW, src)
        if not os.path.exists(path):
            print(f"  (건너뜀: {src} 없음)")
            continue
        mapped = map_dataset(cfg, read_csv(path))
        docs += mapped
        print(f"  [{cfg['domain']}] {src}: {len(mapped)}건")

    joined = spatial_link_vision(docs)
    print(f"  공간조인: 비전 {joined}건 ↔ 공공 포트홀 연계")

    with open(out_path, "w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    by_domain = Counter(d["domain"] for d in docs)
    print(f"정규화 완료: 총 {len(docs)}건 → {out_path}")
    print("  도메인별:", dict(by_domain))
    return docs


if __name__ == "__main__":
    print(f"[ETL] {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    run_etl()
