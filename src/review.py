# -*- coding: utf-8 -*-
"""검수·데이터관리: 문서 목록 조회 / 검수상태 변경 / 변경이력 조회.

제안서 요구 '데이터 변경 이력 관리·검수 상태'의 사용자 인터페이스 계층.
백엔드(schema.set_review_status / doc_change_log)를 CLI·서버 API로 노출한다.

CLI:
  python review.py                      # 검수상태 요약
  python review.py list [status] [domain]   # 문서 목록(검수상태별/도메인별)
  python review.py set <doc_id> <status> [메모...]   # 검수상태 변경(approved|rejected|pending)
  python review.py log [limit]          # 변경 이력
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from schema import connect, set_review_status

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rag.db")
VALID_STATUS = ("pending", "approved", "rejected")


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def status_counts(db_path: str = DEFAULT_DB) -> dict[str, int]:
    conn = connect(db_path)
    rows = conn.execute(
        "SELECT review_status, COUNT(*) c FROM unified_doc GROUP BY review_status").fetchall()
    conn.close()
    return {r["review_status"]: r["c"] for r in rows}


def list_docs(status: str | None = None, domain: str | None = None,
              limit: int = 100, db_path: str = DEFAULT_DB) -> list[dict]:
    conn = connect(db_path)
    where, params = [], []
    if status:
        where.append("review_status=?"); params.append(status)
    if domain:
        where.append("domain=?"); params.append(domain)
    sql = ("SELECT doc_id, title, domain, doc_type, region_name, period, "
           "review_status, updated_at FROM unified_doc")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY domain, doc_id LIMIT ?"
    params.append(limit)
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()
    return rows


def set_status(doc_id: str, status: str, note: str = "",
               db_path: str = DEFAULT_DB) -> dict:
    if status not in VALID_STATUS:
        return {"ok": False, "error": f"status는 {VALID_STATUS} 중 하나여야 합니다."}
    conn = connect(db_path)
    cur = conn.execute("SELECT review_status FROM unified_doc WHERE doc_id=?", (doc_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return {"ok": False, "error": f"존재하지 않는 doc_id: {doc_id}"}
    old = row["review_status"]
    set_review_status(conn, doc_id, status, _ts(), note)  # UPDATE + doc_change_log 기록
    conn.close()
    return {"ok": True, "doc_id": doc_id, "old": old, "new": status, "note": note}


def recent_changes(limit: int = 50, db_path: str = DEFAULT_DB) -> list[dict]:
    conn = connect(db_path)
    rows = [dict(r) for r in conn.execute(
        "SELECT ts, doc_id, action, field, old_value, new_value, note "
        "FROM doc_change_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
    conn.close()
    return rows


def _cli(argv: list[str]) -> None:
    if not argv:
        print("검수상태 요약:", status_counts())
        print("사용법: review.py [list|set|log] ... (파일 상단 docstring 참고)")
        return
    cmd = argv[0]
    if cmd == "list":
        status = argv[1] if len(argv) > 1 else None
        domain = argv[2] if len(argv) > 2 else None
        rows = list_docs(status, domain)
        print(f"문서 {len(rows)}건 (status={status or '전체'}, domain={domain or '전체'})")
        for r in rows[:50]:
            print(f"  [{r['review_status']:>8}] {r['doc_id']}  | {r['domain']} | {r['title']}")
    elif cmd == "set":
        if len(argv) < 3:
            print("사용법: review.py set <doc_id> <approved|rejected|pending> [메모]")
            return
        res = set_status(argv[1], argv[2], " ".join(argv[3:]))
        if res.get("ok"):
            print(f"✅ 검수 변경: {res['doc_id']}  {res['old']} → {res['new']}"
                  + (f"  (메모: {res['note']})" if res["note"] else ""))
        else:
            print("❌", res["error"])
    elif cmd == "log":
        limit = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 50
        rows = recent_changes(limit)
        print(f"변경 이력 {len(rows)}건 (최신순):")
        for r in rows:
            extra = f" {r['field']}: {r['old_value']}→{r['new_value']}" if r["field"] else ""
            note = f"  ({r['note']})" if r["note"] else ""
            print(f"  {r['ts']} | {r['action']:>6} | {r['doc_id']}{extra}{note}")
    else:
        print(f"알 수 없는 명령: {cmd}")


if __name__ == "__main__":
    _cli(sys.argv[1:])
