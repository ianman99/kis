"""report_final.csv 의 (datetime, stock_code) 기준으로
t 부터 t 직후 1000개 1분봉을 KIS OPEN API 로 조회하여
price.csv 로 저장한다.

- datetime 의 '분'을 t 라고 가정한다.
- 조회 범위: 거래 분봉 '개수' 기준. t 시점 봉 ~ t 이후 1000개 봉
  (t 시점 봉 포함). 장 운영시간(09:00~15:30)의 분봉만 카운트하며,
  야간/휴장 갭은 건너뛰고 다음 거래일로 이어서 센다.
- '정상 공시' = t봉 포함 정확히 1001봉이 모두 정규장(09:00~15:30)에
  들어온 경우만 인정한다. 조건 미달 공시(t봉 없음 / 봉 수 부족 /
  시간외 봉 혼입)는 price.csv 에 담지 않고 report_final.csv 에서도
  삭제(덮어쓰기)한다.
- 결과 컬럼: stock_code, datetime, open, high, low, close, volume
"""

import time
import requests
import pandas as pd
from datetime import date, datetime, timedelta
from kis_auth import get_auth_headers, BASE_URL

REPORT_PATH = "./data/report_final.csv"
OUT_PATH    = "./data/price.csv"

BARS_AFTER  = 1000       # t 이후 봉 개수
DAY_GUARD   = 40         # 거래일 탐색 안전 한도 (무한루프 방지)

MAX_RPS     = 10         # 초당 최대 호출 수 (한도 18 대비 안전 마진)
MARKET_OPEN  = "090000"  # 장 시작
MARKET_CLOSE = "153000"  # 장 마감

URL = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice"


def _make_headers() -> dict:
    h = get_auth_headers()
    h["tr_id"]    = "FHKST03010230"
    h["custtype"] = "P"
    return h


def fetch_page(stock_code: str, date_str: str, time_str: str) -> list:
    resp = requests.get(
        URL,
        headers=_make_headers(),
        params={
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD":         stock_code,
            "FID_INPUT_DATE_1":       date_str,
            "FID_INPUT_HOUR_1":       time_str,
            "FID_PW_DATA_INCU_YN":    "Y",
            "FID_FAKE_TICK_INCU_YN":  "",
        },
        timeout=10,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("rt_cd") != "0":
        raise RuntimeError(f"API 오류 [{stock_code} {date_str} {time_str}]: {body.get('msg1')}")
    return body.get("output2", [])


def prev_minute(time_str: str) -> str:
    """HHMMSS 문자열에서 1분을 뺀 시간 반환."""
    h, m = int(time_str[:2]), int(time_str[2:4])
    total_min = h * 60 + m - 1
    return f"{total_min // 60:02d}{total_min % 60:02d}00"


def fetch_day(stock_code: str, date_str: str, start_time: str, stop_time: str,
              call_log: list) -> list:
    """하루치 분봉을 역방향 커서로 수집.

    start_time(포함) 에서 시작해 stop_time(포함) 까지 거슬러 올라가며 수집한다.
    """
    all_rows: list[dict] = []
    seen:     set[str]   = set()
    query_time = start_time
    prev_earliest: str | None = None

    while True:
        throttle(call_log)
        rows = fetch_page(stock_code, date_str, query_time)
        if not rows:
            break

        new_rows = [r for r in rows if r["stck_cntg_hour"] not in seen]
        for r in new_rows:
            seen.add(r["stck_cntg_hour"])
        all_rows.extend(new_rows)

        earliest = min(r["stck_cntg_hour"] for r in rows)
        if earliest <= stop_time:
            break

        # 진전 없음 방지: 거래가 희소해 그날 첫 체결이 09:00 이후인 종목은
        # 커서를 더 내려도 같은 earliest 만 반복 수신되어 무한루프가 된다.
        # earliest 가 더 이상 작아지지 않으면 중단한다.
        if prev_earliest is not None and earliest >= prev_earliest:
            break
        prev_earliest = earliest

        next_time = prev_minute(earliest)
        if next_time <= stop_time:
            break
        query_time = next_time

    return all_rows


def fetch_full_day(stock_code: str, d: date, call_log: list) -> list:
    """해당 거래일의 장 전체(09:00~15:30) 분봉을 수집."""
    return fetch_day(stock_code, d.strftime("%Y%m%d"), MARKET_CLOSE, MARKET_OPEN, call_log)


def _to_dt(r: dict) -> datetime:
    return datetime.strptime(r["stck_bsop_date"] + r["stck_cntg_hour"], "%Y%m%d%H%M%S")


def collect_bars(stock_code: str, t: datetime, call_log: list) -> dict:
    """t 기준 거래일을 정방향으로 탐색하며 분봉을 dict(datetime->row) 로 수집.

    t 이후 봉이 BARS_AFTER 개 모일 때까지 거래일을 진행하며
    장 전체를 받아 모은다.
    """
    bars: dict[datetime, dict] = {}
    fetched: set[date] = set()

    def ensure_day(d: date) -> None:
        if d in fetched or d.weekday() >= 5:
            return
        for r in fetch_full_day(stock_code, d, call_log):
            bars[_to_dt(r)] = r
        fetched.add(d)

    # 정방향: t 이후 봉 1000개 확보
    d, guard = t.date(), 0
    while True:
        ensure_day(d)
        if sum(1 for dt in bars if dt > t) >= BARS_AFTER:
            break
        d += timedelta(days=1)
        guard += 1
        if guard > DAY_GUARD:
            break

    return bars


def throttle(call_log: list) -> None:
    """슬라이딩 윈도우 방식으로 초당 MAX_RPS 이하 유지."""
    now = time.monotonic()
    call_log[:] = [t for t in call_log if now - t < 1.0]
    if len(call_log) >= MAX_RPS:
        sleep_sec = 1.0 - (now - call_log[0]) + 0.01
        if sleep_sec > 0:
            time.sleep(sleep_sec)
    call_log.append(time.monotonic())


EMPTY_COLS = ["stock_code", "datetime", "open", "high", "low", "close", "volume"]


def build_df(stock_code: str, bars: dict, t: datetime) -> pd.DataFrame:
    """수집한 봉에서 t ~ t 이후 1000개(t 봉 포함)를 잘라 정리."""
    if not bars:
        return pd.DataFrame(columns=EMPTY_COLS)

    ordered = sorted(bars)  # datetime 오름차순
    at    = [dt for dt in ordered if dt == t]
    after = [dt for dt in ordered if dt > t][:BARS_AFTER]
    selected = at + after

    df = pd.DataFrame(bars[dt] for dt in selected)
    df["datetime"] = pd.to_datetime(
        df["stck_bsop_date"] + df["stck_cntg_hour"], format="%Y%m%d%H%M%S"
    )
    df = df.rename(columns={
        "stck_oprc": "open",
        "stck_hgpr": "high",
        "stck_lwpr": "low",
        "stck_prpr": "close",
        "cntg_vol":  "volume",
    })
    df["stock_code"] = stock_code

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.sort_values("datetime").reset_index(drop=True)
    return df[EMPTY_COLS]


def main():
    report = pd.read_csv(REPORT_PATH, dtype={"stock_code": str})
    report["stock_code"] = report["stock_code"].str.zfill(6)
    report["datetime"] = pd.to_datetime(report["datetime"])

    call_log: list[float] = []
    frames:   list[pd.DataFrame] = []
    keep_idx: list = []                    # 정상 공시로 판정해 유지할 report 행
    dropped:  list[tuple] = []             # 제외한 (종목, t, 사유)

    expected = 1 + BARS_AFTER              # 정상 봉 개수: t봉 1 + 이후 1000

    for i, row in report.iterrows():
        stock_code = row["stock_code"]
        t = row["datetime"].to_pydatetime().replace(second=0, microsecond=0)

        print(f"[{i+1}/{len(report)}] {stock_code} t={t}  "
              f"(t봉 ~ 이후 {BARS_AFTER}봉) 조회 중...", end=" ", flush=True)

        bars = collect_bars(stock_code, t, call_log)
        df = build_df(stock_code, bars, t)

        # 정상 공시 판정: ① t봉 존재 ② 정확히 1001봉 ③ 전부 정규장(09:00~15:30).
        # 하나라도 어긋나면 price / report_final 양쪽에서 제외한다.
        if t not in bars:
            reason = "t봉 없음"
        elif len(df) != expected:
            reason = f"{len(df)}봉(≠{expected})"
        elif not df["datetime"].dt.strftime("%H%M%S").between(MARKET_OPEN, MARKET_CLOSE).all():
            reason = "시간외 봉 포함"
        else:
            reason = None

        if reason:
            dropped.append((stock_code, t, reason))
            print(f"제외 ({reason})")
            continue

        frames.append(df)
        keep_idx.append(i)
        print(f"{len(df)}건")

    # 정상 공시만 price.csv 로 저장하고, 제외분을 뺀 report_final.csv 로 덮어쓴다.
    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=EMPTY_COLS)
    result.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    report.loc[keep_idx].to_csv(REPORT_PATH, index=False, encoding="utf-8-sig")

    print(f"\n총 {len(result)}건 → {OUT_PATH}")
    print(f"공시 {len(report)}건 중 유지 {len(keep_idx)}건 / 제외 {len(dropped)}건 → {REPORT_PATH}")
    for code, t, reason in dropped:
        print(f"  제외: {code} t={t} ({reason})")
    if not result.empty:
        print(result.head(10).to_string())


if __name__ == "__main__":
    main()
