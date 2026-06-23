"""하이브리드 검색: Dense(임베딩) + Sparse(BM25) → RRF 융합 + 메타 필터.

또한 정형 집계(stats_query)를 제공한다. 이 두 함수가 에이전트의 도구(tool)가 된다.
"""
from __future__ import annotations

import json
import math
import os
import re
from collections import Counter, defaultdict
from typing import Any, Optional

from embeddings import Embeddings, cosine
from schema import connect, row_to_dict

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rag.db")
_TOKEN = re.compile(r"[0-9a-zA-Z]+|[가-힣]+")
_emb = Embeddings()


def _tokenize(text: str) -> list[str]:
    out: list[str] = []
    for m in _TOKEN.findall(text.lower()):
        if re.match(r"[가-힣]+", m) and len(m) >= 2:
            out += [m[i:i + 2] for i in range(len(m) - 1)]
        else:
            out.append(m)
    return out


class Index:
    """SQLite 행을 메모리에 적재해 BM25 + 코사인 검색 (프로토타입 규모)."""

    def __init__(self, db_path: str = DEFAULT_DB) -> None:
        self.db_path = db_path
        conn = connect(db_path)
        self.rows = [dict(r) for r in conn.execute("SELECT * FROM unified_doc")]
        conn.close()
        self.docs = {r["doc_id"]: r for r in self.rows}
        self._build_bm25()

    def _build_bm25(self) -> None:
        self.toks = {r["doc_id"]: _tokenize(f"{r['title']} {r['text']} {r['road_name'] or ''}")
                     for r in self.rows}
        self.df: Counter = Counter()
        for tl in self.toks.values():
            self.df.update(set(tl))
        self.N = max(len(self.rows), 1)
        self.avgdl = (sum(len(t) for t in self.toks.values()) / self.N) or 1.0

    SCALAR_FILTERS = ("domain", "doc_type", "source", "sido_cd", "sigungu_cd", "period")

    def _passes(self, r: dict, flt: Optional[dict]) -> bool:
        if not flt:
            return True
        for key in self.SCALAR_FILTERS:
            want = flt.get(key)
            if want and r.get(key) != want:
                return False
        # 지역명 부분일치 (예: "대전")
        if flt.get("region") and flt["region"] not in (r.get("region_name") or ""):
            return False
        # 태그 포함 (예: "미세먼지")
        if flt.get("tag") and flt["tag"] not in (r.get("tags") or ""):
            return False
        return True

    def _bm25_scores(self, query: str, k1: float = 1.5, b: float = 0.75) -> dict[str, float]:
        q = _tokenize(query)
        scores: dict[str, float] = defaultdict(float)
        for r in self.rows:
            did = r["doc_id"]
            tl = self.toks[did]
            tf = Counter(tl)
            dl = len(tl) or 1
            for term in q:
                if term not in tf:
                    continue
                idf = math.log(1 + (self.N - self.df[term] + 0.5) / (self.df[term] + 0.5))
                denom = tf[term] + k1 * (1 - b + b * dl / self.avgdl)
                scores[did] += idf * (tf[term] * (k1 + 1)) / denom
        return scores

    def _dense_scores(self, query: str) -> dict[str, float]:
        qv = _emb.embed([query], input_type="query")[0]
        out: dict[str, float] = {}
        for r in self.rows:
            if r.get("embedding"):
                out[r["doc_id"]] = cosine(qv, json.loads(r["embedding"]))
        return out

    @staticmethod
    def _rank(scores: dict[str, float]) -> dict[str, int]:
        ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        return {did: i + 1 for i, (did, _) in enumerate(ordered)}

    @staticmethod
    def _recency(row: dict) -> float:
        """정보 최신성 점수 0~1 (period 연도 기준, 2020~2026 정규화)."""
        try:
            year = int((row.get("period") or "2020")[:4])
        except ValueError:
            return 0.0
        return max(0.0, min(1.0, (year - 2020) / 6.0))

    def hybrid_search(self, query: str, filters: Optional[dict] = None,
                      k: int = 5, rrf_k: int = 60, recency_weight: float = 0.15
                      ) -> list[dict[str, Any]]:
        """하이브리드 검색 파이프라인:
        (2) Dense + Sparse 병렬 검색 → RRF 융합
        (3) 재정렬(re-ranking): 융합점수에 (6) 정보 최신성 가중치 반영
        그 뒤 메타 필터(대전 등) 적용.
        """
        dense_r = self._rank(self._dense_scores(query))
        sparse_r = self._rank(self._bm25_scores(query))
        fused: dict[str, float] = defaultdict(float)
        for ranks in (dense_r, sparse_r):
            for did, rank in ranks.items():
                fused[did] += 1.0 / (rrf_k + rank)

        # (3) 재정렬: 최신 문서에 소폭 가산 → 정보 최신성 확보
        reranked = {did: s * (1.0 + recency_weight * self._recency(self.docs[did]))
                    for did, s in fused.items()}

        results = []
        for did, score in sorted(reranked.items(), key=lambda kv: kv[1], reverse=True):
            r = self.docs[did]
            if not self._passes(r, filters):
                continue
            item = row_to_dict_from_plain(r)
            item["_score"] = round(score, 5)
            item["_rrf"] = round(fused[did], 5)
            item["_dense_rank"] = dense_r.get(did)
            item["_sparse_rank"] = sparse_r.get(did)
            results.append(item)
            if len(results) >= k:
                break
        return results

    def domains(self) -> list[dict[str, Any]]:
        """적재된 도메인/데이터 종류 카탈로그 (검색 범위 탐색용)."""
        agg: dict[tuple, int] = defaultdict(int)
        for r in self.rows:
            agg[(r.get("domain") or "기타", r.get("doc_type"))] += 1
        out: dict[str, dict] = {}
        for (dom, dt), n in agg.items():
            out.setdefault(dom, {"domain": dom, "count": 0, "doc_types": []})
            out[dom]["count"] += n
            out[dom]["doc_types"].append(f"{dt}({n})")
        return sorted(out.values(), key=lambda x: x["count"], reverse=True)

    def stats_query(self, metric: str = "count", group_by: str = "surface",
                    filters: Optional[dict] = None) -> list[dict[str, Any]]:
        """정형 집계: metrics JSON에서 metric을 group_by 별로 합산."""
        agg: dict[str, float] = defaultdict(float)
        for r in self.rows:
            if not self._passes(r, filters):
                continue
            m = json.loads(r["metrics"]) if r.get("metrics") else {}
            if metric not in m:
                continue
            if group_by in m:                       # 범주형 지표(노면상태 등)
                key = str(m[group_by])
            elif r.get(group_by) is not None:        # 행 컬럼(region_name, domain 등)
                key = str(r[group_by])
            else:
                continue                             # 해당 그룹키 없는 행은 제외
            agg[key] += float(m[metric])
        return [{"group": g, metric: v} for g, v in
                sorted(agg.items(), key=lambda kv: kv[1], reverse=True)]


def row_to_dict_from_plain(r: dict) -> dict[str, Any]:
    d = dict(r)
    d["metrics"] = json.loads(d["metrics"]) if d.get("metrics") else {}
    d["provenance"] = json.loads(d["provenance"]) if d.get("provenance") else {}
    d.pop("embedding", None)
    return d


if __name__ == "__main__":
    idx = Index()
    print("== 적재 도메인 ==")
    for d in idx.domains():
        print(f"  {d['domain']}: {d['count']}건 {d['doc_types']}")
    for q, flt in [("대전 미세먼지 어때", {"domain": "대기환경"}),
                   ("화재가 많은 지역", {"domain": "재난안전"}),
                   ("유성구 포트홀", {"region": "대전"})]:
        print(f"== 검색: '{q}' (filter={flt}) ==")
        for r in idx.hybrid_search(q, filters=flt, k=3):
            print(f"  [{r['_score']}] {r['title']}")
