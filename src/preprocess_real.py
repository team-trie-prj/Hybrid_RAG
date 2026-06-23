# -*- coding: utf-8 -*-
"""실데이터(루트 원본 CSV) → 시도(+대전 자치구) 단위 집계 → data/raw/ 적재용 CSV.

새로 추가된 공공데이터 원본은 지점/사건 단위(최대 37.5만 행)라서
이 RAG 시스템의 '지역 단위 집계 UnifiedDoc' 설계에 맞게 전처리한다.
regions.py가 해석 가능한 전국 17개 시도 + 대전 5개 자치구 단위로 집계한다.
출력 CSV의 컬럼명은 data/datasets/registry.json 매핑과 1:1로 맞춘다.
"""
from __future__ import annotations

import csv
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW = os.path.join(ROOT, "data", "raw")

# 원본(루트)
SRC = {
    "cctv": os.path.join(ROOT, "CCTV정보.csv"),
    "wifi": os.path.join(ROOT, "무료와이파이정보.csv"),
    "fire": os.path.join(ROOT, "소방청_연간화재통계_20241231.csv"),
    "pothole": os.path.join(ROOT, "한국도로공사_포트홀 및 피해배상 현황_20241231.csv"),
    "surface": os.path.join(ROOT, "한국도로교통공단_노면상태별 교통사고 통계_20241231.csv"),
    "roadtype": os.path.join(ROOT, "한국도로교통공단_사고유형별 도로종류별 교통사고 통계_20241231.csv"),
    "population": os.path.join(ROOT, "행정안전부_지역별(행정동) 성별 연령별 주민등록 인구수_20260531.csv"),
}

# 시도 정규화: 다양한 표기(약칭·정식명·구명) → 표준 명칭(regions.SIDO가 인식하는 이름)
# 주의: '경상북도'는 약칭 '경북'을 부분문자열로 포함하지 않으므로 정식명까지 별칭에 넣어야 함.
SIDO_ALIASES = [
    ("서울특별시", ["서울"]),
    ("부산광역시", ["부산"]),
    ("대구광역시", ["대구"]),
    ("인천광역시", ["인천"]),
    ("광주광역시", ["광주"]),
    ("대전광역시", ["대전"]),
    ("울산광역시", ["울산"]),
    ("세종특별자치시", ["세종"]),
    ("경기도", ["경기"]),
    ("강원특별자치도", ["강원"]),
    ("충청북도", ["충청북", "충북"]),
    ("충청남도", ["충청남", "충남"]),
    ("전북특별자치도", ["전북", "전라북"]),
    ("전라남도", ["전라남", "전남"]),
    ("경상북도", ["경상북", "경북"]),
    ("경상남도", ["경상남", "경남"]),
    ("제주특별자치도", ["제주"]),
]
DAEJEON_GU = {"동구", "중구", "서구", "유성구", "대덕구"}


def canon_sido(raw: str) -> str | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    for full, aliases in SIDO_ALIASES:
        if any(raw.startswith(a) for a in aliases):
            return full
    return None


def read_rows(key: str):
    path = SRC[key]
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            with open(path, encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("preprocess", b"", 0, 1, path)


def num(v) -> float:
    try:
        return float(str(v).replace(",", "").strip() or 0)
    except (ValueError, TypeError):
        return 0.0


def write_csv(name: str, fields: list[str], rows: list[dict]):
    path = os.path.join(RAW, name)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"  → {name}: {len(rows)}건")


def top(label: str, counter: dict, k: int = 5, key=None):
    items = sorted(counter.items(), key=key or (lambda kv: -kv[1]))[:k]
    pretty = ", ".join(f"{n}({v:,.0f})" for n, v in items)
    print(f"    · {label} 상위: {pretty}")


# ── 1) 화재 (시도 + 대전 자치구 집계) ──────────────────────────────
def prep_fire():
    print("[화재] 소방청 연간화재통계")
    rows = read_rows("fire")
    agg = defaultdict(lambda: [0, 0, 0, 0.0])  # 건수, 사망, 부상, 재산피해(천원)
    gu = defaultdict(lambda: [0, 0, 0, 0.0])
    for r in rows:
        sido = canon_sido(r.get("시도"))
        if not sido:
            continue
        a = agg[sido]
        a[0] += 1
        a[1] += num(r.get("사망")); a[2] += num(r.get("부상")); a[3] += num(r.get("재산피해소계"))
        if sido == "대전광역시":
            g = (r.get("시_군_구") or "").strip()
            if g in DAEJEON_GU:
                x = gu[g]
                x[0] += 1
                x[1] += num(r.get("사망")); x[2] += num(r.get("부상")); x[3] += num(r.get("재산피해소계"))
    out = []
    for sido, a in agg.items():
        out.append({"시도": sido, "기준연도": "2024", "화재건수": int(a[0]),
                    "사망자수": int(a[1]), "부상자수": int(a[2]), "재산피해_천원": int(a[3])})
    for g, x in gu.items():
        out.append({"시도": f"대전광역시 {g}", "기준연도": "2024", "화재건수": int(x[0]),
                    "사망자수": int(x[1]), "부상자수": int(x[2]), "재산피해_천원": int(x[3])})
    top("화재건수", {r["시도"]: r["화재건수"] for r in out if " " not in r["시도"]})
    write_csv("fire_incidents.csv",
              ["시도", "기준연도", "화재건수", "사망자수", "부상자수", "재산피해_천원"], out)


# ── 2) 인구 (시도 + 대전 자치구) ──────────────────────────────────
def prep_population():
    print("[인구] 행정안전부 주민등록 인구")
    rows = read_rows("population")
    # 고령(65세 이상) 컬럼명 수집
    sample = rows[0]
    elderly_cols = [c for c in sample
                    if (c.endswith("세남자") or c.endswith("세여자") or "110세이상" in c)
                    and _age_ge(c, 65)]
    agg = defaultdict(lambda: [0, 0, 0, 0])  # 계, 남, 여, 고령
    gu = defaultdict(lambda: [0, 0, 0, 0])
    for r in rows:
        sido = canon_sido(r.get("시도명"))
        if not sido:
            continue
        elderly = int(sum(num(r.get(c)) for c in elderly_cols))
        a = agg[sido]
        a[0] += int(num(r.get("계"))); a[1] += int(num(r.get("남자")))
        a[2] += int(num(r.get("여자"))); a[3] += elderly
        if sido == "대전광역시":
            g = (r.get("시군구명") or "").strip()
            if g in DAEJEON_GU:
                x = gu[g]
                x[0] += int(num(r.get("계"))); x[1] += int(num(r.get("남자")))
                x[2] += int(num(r.get("여자"))); x[3] += elderly
    out = []
    for sido, a in agg.items():
        out.append({"시도": sido, "기준연도": "2026", "인구수": a[0],
                    "남자": a[1], "여자": a[2], "고령인구": a[3]})
    for g, x in gu.items():
        out.append({"시도": f"대전광역시 {g}", "기준연도": "2026", "인구수": x[0],
                    "남자": x[1], "여자": x[2], "고령인구": x[3]})
    top("인구수", {r["시도"]: r["인구수"] for r in out if " " not in r["시도"]})
    write_csv("population.csv",
              ["시도", "기준연도", "인구수", "남자", "여자", "고령인구"], out)


def _age_ge(col: str, threshold: int) -> bool:
    if "110세이상" in col:
        return True
    digits = "".join(ch for ch in col if ch.isdigit())
    return digits.isdigit() and int(digits) >= threshold if digits else False


# ── 3) CCTV (주소에서 시도/대전구 파싱 후 집계) ────────────────────
def prep_cctv():
    print("[생활안전] 방범 CCTV")
    rows = read_rows("cctv")
    agg = defaultdict(lambda: [0, 0])  # 카메라합, 지점수
    gu = defaultdict(lambda: [0, 0])
    for r in rows:
        addr = (r.get("소재지도로명주소") or r.get("소재지지번주소") or "").strip()
        if not addr:
            continue
        toks = addr.split()
        sido = canon_sido(toks[0]) if toks else None
        if not sido:
            continue
        cams = int(num(r.get("카메라대수")) or 1)
        a = agg[sido]; a[0] += cams; a[1] += 1
        if sido == "대전광역시" and len(toks) > 1 and toks[1] in DAEJEON_GU:
            x = gu[toks[1]]; x[0] += cams; x[1] += 1
    out = []
    for sido, a in agg.items():
        out.append({"시도": sido, "기준연도": "2026", "CCTV대수": a[0], "설치지점수": a[1]})
    for g, x in gu.items():
        out.append({"시도": f"대전광역시 {g}", "기준연도": "2026", "CCTV대수": x[0], "설치지점수": x[1]})
    top("CCTV대수", {r["시도"]: r["CCTV대수"] for r in out if " " not in r["시도"]})
    write_csv("safety_cctv.csv",
              ["시도", "기준연도", "CCTV대수", "설치지점수"], out)


# ── 4) 공공와이파이 ───────────────────────────────────────────────
def prep_wifi():
    print("[생활복지] 공공와이파이")
    rows = read_rows("wifi")
    agg = defaultdict(int)
    gu = defaultdict(int)
    for r in rows:
        sido = canon_sido(r.get("설치시도명"))
        if not sido:
            continue
        agg[sido] += 1
        if sido == "대전광역시":
            g = (r.get("설치시군구명") or "").strip()
            if g in DAEJEON_GU:
                gu[g] += 1
    out = [{"시도": s, "기준연도": "2026", "AP설치수": c} for s, c in agg.items()]
    out += [{"시도": f"대전광역시 {g}", "기준연도": "2026", "AP설치수": c} for g, c in gu.items()]
    top("AP설치수", {r["시도"]: r["AP설치수"] for r in out if " " not in r["시도"]})
    write_csv("public_wifi.csv", ["시도", "기준연도", "AP설치수"], out)


# ── 5) 포트홀 (wide → long: 노선 × 연도) ──────────────────────────
def prep_pothole():
    print("[도로시설] 고속도로 포트홀")
    rows = read_rows("pothole")
    out = []
    for r in rows:
        route = (r.get("노선명") or "").strip()
        if not route:
            continue
        for y in ("2020", "2021", "2022", "2023", "2024"):
            occ = num(r.get(f"{y}년 발생(건)"))
            clm = num(r.get(f"{y}년 배상(건)"))
            amt = num(r.get(f"{y}년 배상금액(백만원)"))
            if occ == 0 and clm == 0 and amt == 0:
                continue
            out.append({"노선명": route, "기준연도": y, "포트홀발생건수": int(occ),
                        "배상건수": int(clm), "배상금액_백만원": int(amt)})
    write_csv("korea_expressway_pothole.csv",
              ["노선명", "기준연도", "포트홀발생건수", "배상건수", "배상금액_백만원"], out)


# ── 6) 노면상태별 교통사고 (전국) ─────────────────────────────────
def prep_surface():
    print("[교통안전] 노면상태별 교통사고")
    rows = read_rows("surface")
    out = []
    for r in rows:
        injury = int(num(r.get("중상자수")) + num(r.get("경상자수")) + num(r.get("부상신고자수")))
        out.append({"시도": "전국", "기준연도": "2024", "노면상태": (r.get("노면상태") or "").strip(),
                    "사고건수": int(num(r.get("사고건수"))), "사망자수": int(num(r.get("사망자수"))),
                    "부상자수": injury})
    write_csv("koroad_surface_accident.csv",
              ["시도", "기준연도", "노면상태", "사고건수", "사망자수", "부상자수"], out)


# ── 7) 도로종류별 교통사고 (전국, 도로종류로 집계) ────────────────
def prep_roadtype():
    print("[교통안전] 도로종류별 교통사고")
    rows = read_rows("roadtype")
    agg = defaultdict(lambda: [0, 0, 0])
    for r in rows:
        rt = (r.get("도로종류") or "").strip()
        if not rt:
            continue
        a = agg[rt]
        a[0] += int(num(r.get("사고건수"))); a[1] += int(num(r.get("사망자수")))
        a[2] += int(num(r.get("중상자수")) + num(r.get("경상자수")) + num(r.get("부상신고자수")))
    out = [{"시도": "전국", "기준연도": "2024", "도로종류": rt,
            "사고건수": a[0], "사망자수": a[1], "부상자수": a[2]} for rt, a in agg.items()]
    write_csv("koroad_roadtype_accident.csv",
              ["시도", "기준연도", "도로종류", "사고건수", "사망자수", "부상자수"], out)


if __name__ == "__main__":
    print("=== 실데이터 전처리: 지점/사건 단위 → 지역 단위 집계 ===")
    prep_fire(); prep_population(); prep_cctv(); prep_wifi()
    prep_pothole(); prep_surface(); prep_roadtype()
    print("=== 전처리 완료: data/raw/ 갱신됨 ===")
