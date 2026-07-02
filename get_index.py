"""코스피/코스닥 업종 일자별지수를 KIS OPEN API 로 조회하여
price_index.csv 로 저장한다.

- 국내업종 일자별지수 API (FHPUP02120000) 사용.
  한 번의 조회에 최대 100건(영업일)까지 반환하므로,
  START_DATE ~ END_DATE 구간을 커버할 때까지 조회 날짜를 뒤로 옮겨가며
  반복 조회(페이지네이션)한다.
- 조회 대상: 코스피(0001), 코스닥(1001).
- 결과 컬럼: date, index_name, open, high, low, close, volume,
  change, change_pct
"""

import time
import requests
import pandas as pd
from datetime import datetime, timedelta
from kis_auth import get_auth_headers, BASE_URL

# ─── 조회 기간 상수 (여기서 직접 설정) ──────────────────────────────
START_DATE = "20250501"   # 시작일 (YYYYMMDD)
END_DATE   = "20260701"   # 종료일 (YYYYMMDD)
# ────────────────────────────────────────────────────────────────

OUT_PATH = "./data/price_index.csv"

# 조회할 업종: (업종코드, 지수명)
INDICES = [
    ("0001", "코스피"),
    ("1001", "코스닥"),
]

MAX_RPS   = 10   # 초당 최대 호출 수 (한도 대비 안전 마진)
DAY_GUARD = 40   # 페이지네이션 안전 한도 (무한루프 방지)

URL = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-index-daily-price"


def _make_headers() -> dict:
    h = get_auth_headers()
    h["tr_id"]    = "FHPUP02120000"
    h["custtype"] = "P"
    return h


def fetch_page(index_code: str, date_str: str, call_log: list) -> list:
    """date_str(입력 날짜) 기준으로 과거 방향 최대 100영업일 지수를 조회."""
    throttle(call_log)
    resp = requests.get(
        URL,
        headers=_make_headers(),
        params={
            "FID_PERIOD_DIV_CODE":    "D",         # 일별
            "FID_COND_MRKT_DIV_CODE": "U",         # 업종
            "FID_INPUT_ISCD":         index_code,
            "FID_INPUT_DATE_1":       date_str,
        },
        timeout=10,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("rt_cd") != "0":
        raise RuntimeError(f"API 오류 [{index_code} {date_str}]: {body.get('msg1')}")
    return body.get("output2", [])


def _prev_day(date_str: str) -> str:
    """YYYYMMDD 문자열에서 하루 전 날짜 반환."""
    d = datetime.strptime(date_str, "%Y%m%d") - timedelta(days=1)
    return d.strftime("%Y%m%d")


def collect_rows(index_code: str, index_name: str, call_log: list) -> list:
    """START_DATE ~ END_DATE 구간의 지수 데이터를 dict 리스트로 수집."""
    rows: dict[str, dict] = {}   # date -> row (중복 제거)
    query_date = END_DATE
    guard = 0

    while query_date >= START_DATE and guard < DAY_GUARD:
        page = fetch_page(index_code, query_date, call_log)
        # 유효 데이터(영업일자 있는 행)만 취한다.
        page = [r for r in page if r.get("stck_bsop_date")]
        if not page:
            break

        for r in page:
            d = r["stck_bsop_date"]
            if START_DATE <= d <= END_DATE:
                rows[d] = r

        earliest = min(r["stck_bsop_date"] for r in page)
        if earliest <= START_DATE:
            break
        # 다음 페이지: 가장 이른 날짜 하루 전부터 다시 과거로 조회.
        query_date = _prev_day(earliest)
        guard += 1

    result = []
    for d in sorted(rows):
        r = rows[d]
        result.append({
            "date":       d,
            "index_name": index_name,
            "open":       _to_float(r.get("bstp_nmix_oprc")),
            "high":       _to_float(r.get("bstp_nmix_hgpr")),
            "low":        _to_float(r.get("bstp_nmix_lwpr")),
            "close":      _to_float(r.get("bstp_nmix_prpr")),
            "volume":     _to_float(r.get("acml_vol")),
            "change":    _to_float(r.get("bstp_nmix_prdy_vrss")),
            "change_pct":   _to_float(r.get("bstp_nmix_prdy_ctrt")),
        })
    return result


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def throttle(call_log: list) -> None:
    """슬라이딩 윈도우 방식으로 초당 MAX_RPS 이하 유지."""
    now = time.monotonic()
    call_log[:] = [t for t in call_log if now - t < 1.0]
    if len(call_log) >= MAX_RPS:
        sleep_sec = 1.0 - (now - call_log[0]) + 0.01
        if sleep_sec > 0:
            time.sleep(sleep_sec)
    call_log.append(time.monotonic())


COLS = ["date", "index_name", "open", "high", "low", "close",
        "volume", "change", "change_pct"]


def main():
    call_log: list[float] = []
    all_rows: list[dict] = []

    for code, name in INDICES:
        print(f"{name}({code}) {START_DATE}~{END_DATE} 조회 중...", end=" ", flush=True)
        rows = collect_rows(code, name, call_log)
        all_rows.extend(rows)
        print(f"{len(rows)}건")

    df = pd.DataFrame(all_rows, columns=COLS)
    df = df.sort_values(["index_name", "date"]).reset_index(drop=True)
    df.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")

    print(f"\n총 {len(df)}건 → {OUT_PATH}")
    if not df.empty:
        print(df.head(10).to_string())


if __name__ == "__main__":
    main()
