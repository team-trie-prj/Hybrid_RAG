"""UI 백엔드: 표준 라이브러리 http 서버 (의존성 없음).

엔드포인트
  GET  /                 → web/index.html
  POST /api/ask          {question} → {answer, provider, intent, hits, stats, sources}
  GET  /api/history      → 질의 이력
  POST /api/report       {question} → {path}  (.docx 생성)
  GET  /download/report  → 생성된 보고서 다운로드

실행:  python server.py   →  http://localhost:8000
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import agent
import report as report_mod
import review as review_mod
from retrieve import Index

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
REPORT_PATH = os.path.join(ROOT, "report_output.docx")

_IDX = Index()  # 서버 기동 시 1회 로드


def _ask_payload(question: str) -> dict:
    answer = agent.ask(question, _IDX)
    intent, flt, metric, label, group_by = report_mod._plan(question)
    hits = _IDX.hybrid_search(question, filters=flt, k=6)
    agg_flt = dict(flt)
    if group_by == "region_name":
        agg_flt.pop("sido_cd", None); agg_flt.pop("sigungu_cd", None)
    stats = _IDX.stats_query(metric, group_by, agg_flt)[:8]
    for s in stats:
        s["label"] = s["group"]
        s["value"] = s.get(metric, 0)
    sources = sorted({h["provenance"].get("url", "") for h in hits if h["provenance"].get("url")})
    return {"answer": answer, "intent": intent,
            "domain": intent["domain"], "region": intent["region"],
            "metric_label": label, "group_by": group_by,
            "hits": hits, "stats": stats, "sources": [s for s in sources if s]}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 콘솔 소음 억제
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(os.path.join(WEB, "index.html"), "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        if self.path == "/api/history":
            return self._send(200, agent.history(_IDX, 30))
        if self.path == "/api/domains":
            return self._send(200, _IDX.domains())
        if self.path.startswith("/api/docs"):
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            status = (qs.get("status") or [None])[0]
            domain = (qs.get("domain") or [None])[0]
            return self._send(200, {"counts": review_mod.status_counts(),
                                    "docs": review_mod.list_docs(status, domain, limit=200)})
        if self.path == "/api/changelog":
            return self._send(200, review_mod.recent_changes(50))
        if self.path == "/download/report":
            if not os.path.exists(REPORT_PATH):
                return self._send(404, {"error": "보고서가 아직 생성되지 않았습니다."})
            with open(REPORT_PATH, "rb") as f:
                self.send_response(200)
                self.send_header("Content-Type",
                                 "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
                self.send_header("Content-Disposition", 'attachment; filename="report.docx"')
                body = f.read()
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                return self.wfile.write(body)
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "invalid json"})

        if self.path == "/api/review":  # 검수 상태 변경 (question 불필요)
            doc_id = (payload.get("doc_id") or "").strip()
            status = (payload.get("status") or "").strip()
            if not doc_id or not status:
                return self._send(400, {"error": "doc_id, status 필요"})
            return self._send(200, review_mod.set_status(doc_id, status,
                                                         payload.get("note") or ""))

        question = (payload.get("question") or "").strip()
        if not question:
            return self._send(400, {"error": "question 필요"})

        if self.path == "/api/ask":
            return self._send(200, _ask_payload(question))
        if self.path == "/api/report":
            path = report_mod.generate_report(question, _IDX, REPORT_PATH)
            return self._send(200, {"path": path, "download": "/download/report"})
        return self._send(404, {"error": "not found"})


def main(port: int = 8000):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"UI 서버 실행 → http://localhost:{port}  (Ctrl+C 종료)")
    srv.serve_forever()


if __name__ == "__main__":
    import sys
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8000)
