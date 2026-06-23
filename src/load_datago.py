"""실데이터 적재: data.go.kr OpenAPI → 범용 매퍼 → 정규화 JSONL.

레지스트리 config에 "api" 블록이 있는 데이터셋을 인증키로 수집한다.
파일(CSV) 데이터셋은 etl.py를 쓰면 된다.

config의 api 블록 예시:
  "api": {
    "endpoint": "https://apis.data.go.kr/...",
    "params": {"...": "..."},
    "items_path": ["response", "body", "items", "item"]
  }

사용:
  $env:DATAGO_SERVICE_KEY = "발급키"
  python load_datago.py 15130420        # 특정 dataset_id 수집
  python load_datago.py --all           # api 블록 있는 모든 config 수집
  그 후:  python ingest.py ../data/normalized.jsonl
"""
from __future__ import annotations

import json
import os
import sys

import datago_client
import etl
import mapper

OUT = etl.OUT_JSONL


def load_one(cfg: dict) -> list[dict]:
    api = cfg.get("api")
    if not api:
        print(f"  (스킵: {cfg['dataset_id']} — api 블록 없음. CSV면 etl.py 사용)")
        return []
    rows = datago_client.fetch_all(
        api["endpoint"], api.get("params"), rows=api.get("rows", 100),
        max_pages=api.get("max_pages", 50), items_path=tuple(api.get("items_path", [])))
    docs = [mapper.build_doc(r, cfg, i) for i, r in enumerate(rows)]
    print(f"  [{cfg.get('domain')}] {cfg['dataset_id']}: API {len(docs)}건")
    return docs


def main(argv: list[str]) -> None:
    if not datago_client.has_key():
        print("인증키 없음. datago_client.py 상단 가이드 참고 후 "
              "$env:DATAGO_SERVICE_KEY 설정.")
        return
    registry = etl.load_registry()
    if argv and argv[0] == "--all":
        targets = [c for c in registry if c.get("api")]
    else:
        targets = [c for c in registry if c["dataset_id"] in set(argv)]
    if not targets:
        print("대상 config 없음 (dataset_id 또는 --all 지정, 그리고 api 블록 필요).")
        return

    docs: list[dict] = []
    for cfg in targets:
        docs += load_one(cfg)
    docs = etl.spatial_link_vision(docs) and docs or docs  # 공간조인(있으면)

    # 기존 normalized.jsonl에 append (중복 doc_id는 ingest 시 최신본으로 대체됨)
    with open(OUT, "a", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(f"수집 완료: {len(docs)}건 추가 → {OUT}\n  다음: python ingest.py {OUT}")


if __name__ == "__main__":
    main(sys.argv[1:])
