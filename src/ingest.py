"""적재: JSONL(UnifiedDoc) → SQLite 정형 스토어 + 임베딩.

실전 인덱싱 파이프라인의 축소판:
  원천 → 정규화(UnifiedDoc) → 임베딩 → 적재(정형/벡터)
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from embeddings import Embeddings
from schema import UnifiedDoc, connect, init_db, log_change

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_DATA = os.path.join(ROOT, "data", "sample_daejeon.jsonl")
DEFAULT_DB = os.path.join(ROOT, "rag.db")


def load_jsonl(path: str) -> list[UnifiedDoc]:
    docs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                docs.append(UnifiedDoc.from_json(json.loads(line)))
    return docs


def ingest(data_path: str = DEFAULT_DATA, db_path: str = DEFAULT_DB) -> int:
    docs = load_jsonl(data_path)
    emb = Embeddings()
    # 임베딩 대상 = 제목 + 본문 (검색 재현율 향상)
    vectors = emb.embed([f"{d.title}\n{d.text}" for d in docs], input_type="document")

    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = connect(db_path)
    conn.execute("DROP TABLE IF EXISTS unified_doc")  # 스키마 변경 반영 위해 재생성
    init_db(conn)  # 이력 테이블(query_history/doc_change_log)은 IF NOT EXISTS로 보존
    conn.executemany(UnifiedDoc.INSERT_SQL, [d.to_row(v, ts) for d, v in zip(docs, vectors)])
    for d in docs:
        log_change(conn, ts, d.doc_id, "insert", note=f"source={d.source}")
    conn.commit()
    conn.close()
    print(f"적재 완료: {len(docs)}건 → {db_path}  (임베딩 제공자: {emb.provider})")
    return len(docs)


if __name__ == "__main__":
    import sys
    ingest(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DATA)
