"""통합 데이터 구조(UnifiedDoc)와 SQLite DDL.

프로토타입은 SQLite 단일 파일로 정형/벡터/메타를 모두 보관한다.
실전 전환 시 PostgreSQL + PostGIS(geom) + pgvector(embedding)로 그대로 매핑된다.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Optional

# 대전 자치구 행정표준코드 (sigungu_cd) — 메타 필터/조인 키
DAEJEON_SIGUNGU = {
    "30000": "대전광역시(전체)",
    "30110": "동구",
    "30140": "중구",
    "30170": "서구",
    "30200": "유성구",
    "30230": "대덕구",
}

DDL = """
CREATE TABLE IF NOT EXISTS unified_doc (
    doc_id       TEXT PRIMARY KEY,
    source       TEXT NOT NULL,
    domain       TEXT,    -- 교통안전 | 대기환경 | 재난안전 | 생활복지 | 인구 | 도로시설 ...
    doc_type     TEXT NOT NULL,
    title        TEXT,
    text         TEXT,
    tags         TEXT,    -- 공백구분 키워드 (검색/필터 보조)
    lat          REAL,
    lng          REAL,
    sido_cd      TEXT,
    sigungu_cd   TEXT,
    region_name  TEXT,
    road_name    TEXT,
    road_link_id TEXT,
    occurred_at  TEXT,
    period       TEXT,
    metrics      TEXT,   -- JSON
    provenance   TEXT,   -- JSON
    embedding    TEXT,   -- JSON float[] (실전: pgvector 컬럼)
    review_status TEXT DEFAULT 'pending',  -- pending|approved|rejected (검수 상태)
    content_hash TEXT,   -- 변경 감지용 해시
    updated_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_doc_filter ON unified_doc (domain, sido_cd, doc_type, period);

-- 질의/응답 이력 (프롬프트, 응답, 의도, 사용 도구)
CREATE TABLE IF NOT EXISTS query_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT,
    question   TEXT,
    intent     TEXT,    -- JSON
    tools_used TEXT,    -- JSON list
    answer     TEXT,
    provider   TEXT     -- gemini | offline
);

-- 데이터 변경/수정 이력 (적재·검수·수정 추적)
CREATE TABLE IF NOT EXISTS doc_change_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT,
    doc_id    TEXT,
    action    TEXT,     -- insert | update | review | delete
    field     TEXT,     -- 변경 필드 (review 시 review_status 등)
    old_value TEXT,
    new_value TEXT,
    note      TEXT
);
"""


@dataclass
class UnifiedDoc:
    doc_id: str
    source: str
    doc_type: str
    title: str
    text: str
    domain: str = ""
    tags: list[str] = field(default_factory=list)
    geo: dict[str, Any] = field(default_factory=dict)
    time: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "UnifiedDoc":
        return cls(
            doc_id=raw["doc_id"], source=raw["source"], doc_type=raw["doc_type"],
            title=raw.get("title", ""), text=raw.get("text", ""),
            domain=raw.get("domain", ""), tags=raw.get("tags", []),
            geo=raw.get("geo", {}), time=raw.get("time", {}),
            metrics=raw.get("metrics", {}), provenance=raw.get("provenance", {}),
        )

    def content_hash(self) -> str:
        payload = json.dumps([self.title, self.text, self.geo, self.metrics],
                             ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]

    def to_row(self, embedding: Optional[list[float]], updated_at: str,
               review_status: str = "pending") -> tuple:
        g, t = self.geo, self.time
        return (
            self.doc_id, self.source, self.domain, self.doc_type, self.title, self.text,
            " ".join(self.tags),
            g.get("lat"), g.get("lng"), g.get("sido_cd"), g.get("sigungu_cd"),
            g.get("region_name"), g.get("road_name"), g.get("road_link_id"),
            t.get("occurred_at"), t.get("period"),
            json.dumps(self.metrics, ensure_ascii=False),
            json.dumps(self.provenance, ensure_ascii=False),
            json.dumps(embedding) if embedding is not None else None,
            review_status, self.content_hash(), updated_at,
        )

    INSERT_COLS = (
        "doc_id, source, domain, doc_type, title, text, tags, lat, lng, sido_cd, "
        "sigungu_cd, region_name, road_name, road_link_id, occurred_at, period, "
        "metrics, provenance, embedding, review_status, content_hash, updated_at"
    )
    INSERT_SQL = f"INSERT INTO unified_doc ({INSERT_COLS}) VALUES ({','.join(['?'] * 22)})"


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)
    conn.commit()


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["metrics"] = json.loads(d["metrics"]) if d.get("metrics") else {}
    d["provenance"] = json.loads(d["provenance"]) if d.get("provenance") else {}
    d.pop("embedding", None)  # 응답에서 벡터는 제외
    return d


# ─────────────────────────────────────────── 이력 관리 헬퍼
def log_query(conn: sqlite3.Connection, ts: str, question: str, intent: dict,
              tools_used: list[str], answer: str, provider: str) -> None:
    conn.execute(
        "INSERT INTO query_history (ts, question, intent, tools_used, answer, provider) "
        "VALUES (?,?,?,?,?,?)",
        (ts, question, json.dumps(intent, ensure_ascii=False),
         json.dumps(tools_used, ensure_ascii=False), answer, provider),
    )
    conn.commit()


def log_change(conn: sqlite3.Connection, ts: str, doc_id: str, action: str,
               field: str = "", old_value: str = "", new_value: str = "",
               note: str = "") -> None:
    conn.execute(
        "INSERT INTO doc_change_log (ts, doc_id, action, field, old_value, new_value, note) "
        "VALUES (?,?,?,?,?,?,?)",
        (ts, doc_id, action, field, old_value, new_value, note),
    )
    conn.commit()


def get_history(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM query_history ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["intent"] = json.loads(d["intent"]) if d.get("intent") else {}
        d["tools_used"] = json.loads(d["tools_used"]) if d.get("tools_used") else []
        out.append(d)
    return out


def set_review_status(conn: sqlite3.Connection, doc_id: str, status: str,
                      ts: str, note: str = "") -> None:
    cur = conn.execute("SELECT review_status FROM unified_doc WHERE doc_id=?", (doc_id,))
    row = cur.fetchone()
    old = row["review_status"] if row else None
    conn.execute("UPDATE unified_doc SET review_status=?, updated_at=? WHERE doc_id=?",
                 (status, ts, doc_id))
    log_change(conn, ts, doc_id, "review", "review_status", str(old), status, note)
    conn.commit()
