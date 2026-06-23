"""단일 종목의 기간별 1분봉(분봉) 데이터 수집 스크립트.

지정한 종목(STOCK_CODE)에 대해 START_DATE ~ END_DATE 사이의
거래일마다 장 전체(09:00~15:30) 1분봉을 KIS Open API 로 조회하여
하나의 CSV(minute_chart_<종목코드>.csv)로 저장한다.

KIS 분봉 조회 API 는 한 번 호출에 기준시각부터 과거 방향으로
일정 개수(약 100여 건)만 반환하므로, 하루 전체를 받으려면
'역방향 커서'로 시각을 거슬러 올라가며 반복 호출한다.
"""

import time
import requests
import pandas as pd
from datetime import date, timedelta
from kis_auth import get_auth_headers, BASE_URL

# ── 수집 설정 ────────────────────────────────────────────────
STOCK_CODE  = "005930"          # 조회할 종목코드 (예: 005930 = 삼성전자)
START_DATE  = date(2026, 6, 18)  # 수집 시작일
END_DATE    = date(2026, 6, 23)   # 수집 종료일
MAX_RPS     = 10        # 초당 최대 호출 수 (한도 18 대비 안전 마진)
MARKET_OPEN = "090000"  # 장 시작 시각(HHMMSS). 역방향 수집의 종료 기준.

# 국내주식 일별분봉조회 엔드포인트
URL = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice"


def _make_headers() -> dict:
    """공통 인증 헤더에 이 API 전용 tr_id, custtype 을 더해 반환."""
    h = get_auth_headers()
    h["tr_id"]    = "FHKST03010230"  # 일별분봉조회 거래 ID
    h["custtype"] = "P"              # 고객 구분: P = 개인
    return h


def fetch_page(date_str: str, time_str: str) -> list:
    """기준일(date_str)·기준시각(time_str)으로 한 페이지(분봉 묶음)를 조회.

    API 는 time_str 시각부터 '과거 방향'으로 일정 개수만 돌려준다.
    """
    resp = requests.get(
        URL,
        headers=_make_headers(),
        params={
            "FID_COND_MRKT_DIV_CODE": "J",        # 시장 구분: J = KRX
            "FID_INPUT_ISCD":         STOCK_CODE,  # 종목코드
            "FID_INPUT_DATE_1":       date_str,    # 조회 기준일 YYYYMMDD
            "FID_INPUT_HOUR_1":       time_str,    # 조회 기준시각 HHMMSS
            "FID_PW_DATA_INCU_YN":    "Y",         # 과거 데이터 포함
            "FID_FAKE_TICK_INCU_YN":  "",          # 허봉 포함 여부
        },
        timeout=10,
    )
    resp.raise_for_status()  # HTTP 에러면 예외 발생
    body = resp.json()
    # rt_cd 가 "0" 이 아니면 API 가 업무 오류를 반환한 것.
    if body.get("rt_cd") != "0":
        raise RuntimeError(f"API 오류 [{date_str} {time_str}]: {body.get('msg1')}")
    # 실제 분봉 데이터는 output2 배열에 담겨 온다.
    return body.get("output2", [])


def prev_minute(time_str: str) -> str:
    """HHMMSS 문자열에서 1분을 뺀 시간 반환 (역방향 커서 이동용)."""
    h, m = int(time_str[:2]), int(time_str[2:4])
    total_min = h * 60 + m - 1          # 전체를 '분'으로 환산해 1 뺀다
    return f"{total_min // 60:02d}{total_min % 60:02d}00"  # 다시 HHMM00 으로


def fetch_day(date_str: str, call_log: list) -> list:
    """하루 전체 분봉을 역방향 커서로 수집.

    장 마감(15:30)부터 시작해, 매 응답의 '가장 이른 시각' 1분 전으로
    커서를 옮겨가며 09:00 에 도달할 때까지 반복 조회한다.
    """
    all_rows: list[dict] = []
    seen:     set[str]   = set()   # 이미 받은 체결시각 모음(중복 차단)
    query_time = "153000"          # 첫 조회 기준시각 = 장 마감

    while True:
        throttle(call_log)                       # 속도 제한 준수
        rows = fetch_page(date_str, query_time)  # 한 페이지 조회

        if not rows:
            break  # 더 받을 데이터가 없으면 종료

        # 중복 방지 (같은 체결시간 재수신 차단)
        new_rows = [r for r in rows if r["stck_cntg_hour"] not in seen]
        for r in new_rows:
            seen.add(r["stck_cntg_hour"])
        all_rows.extend(new_rows)

        # 이번 응답에서 가장 이른(과거) 체결시각
        earliest = min(r["stck_cntg_hour"] for r in rows)

        # 장 시작 시간 이전 데이터까지 받았으면 완료
        if earliest <= MARKET_OPEN:
            break

        # 가장 이른 시간에서 1분 전으로 커서 이동
        next_time = prev_minute(earliest)
        if next_time <= MARKET_OPEN:
            break

        query_time = next_time

    return all_rows


def trading_days(start: date, end: date):
    """start~end 사이의 평일(월~금)만 차례로 내보내는 제너레이터.

    (공휴일은 거르지 않지만, 휴장일은 API 가 빈 응답을 주므로 자연히 건너뛴다.)
    """
    d = start
    while d <= end:
        if d.weekday() < 5:  # 0=월 ~ 4=금 만 거래일로 간주
            yield d
        d += timedelta(days=1)


def throttle(call_log: list) -> None:
    """슬라이딩 윈도우 방식으로 초당 MAX_RPS 이하 유지.

    call_log 에 최근 호출 시각을 기록하고, 최근 1초간 호출이 한도에
    찼으면 가장 오래된 호출이 1초를 넘길 때까지 sleep 한다.
    """
    now = time.monotonic()
    # 1초가 지난 과거 호출 기록은 버린다.
    call_log[:] = [t for t in call_log if now - t < 1.0]
    if len(call_log) >= MAX_RPS:
        # 가장 오래된 호출이 1초를 채울 때까지 대기(+0.01 여유).
        sleep_sec = 1.0 - (now - call_log[0]) + 0.01
        if sleep_sec > 0:
            time.sleep(sleep_sec)
    call_log.append(time.monotonic())  # 이번 호출 시각 기록


def main():
    all_rows: list[dict] = []    # 모든 거래일의 분봉을 누적
    call_log: list[float] = []   # 속도 제한 카운터 (전체 실행에서 공유)

    # 거래일마다 하루치 분봉을 수집해 누적한다.
    for trade_date in trading_days(START_DATE, END_DATE):
        date_str = trade_date.strftime("%Y%m%d")
        print(f"[{date_str}] 조회 중...", end=" ", flush=True)

        rows = fetch_day(date_str, call_log)
        all_rows.extend(rows)
        print(f"{len(rows)}건")

    if not all_rows:
        print("조회 결과 없음.")
        return

    # 원본 응답키를 보기 좋은 컬럼명으로 변경.
    df = pd.DataFrame(all_rows)
    df = df.rename(columns={
        "stck_bsop_date": "date",         # 영업일자
        "stck_cntg_hour": "time",         # 체결시각
        "stck_prpr":      "close",        # 종가(현재가)
        "stck_oprc":      "open",         # 시가
        "stck_hgpr":      "high",         # 고가
        "stck_lwpr":      "low",          # 저가
        "cntg_vol":       "volume",       # 거래량
        "acml_tr_pbmn":   "trade_value",  # 누적 거래대금
    })

    # 날짜·시각 순으로 정렬하고, 식별·시간 컬럼을 정리한다.
    df = df.sort_values(["date", "time"]).reset_index(drop=True)
    df["code"] = STOCK_CODE  # 종목코드 컬럼 추가
    # date(YYYYMMDD) + time(HHMMSS) 문자열을 합쳐 datetime 타입으로 변환.
    df["datetime"] = pd.to_datetime(df["date"] + df["time"], format="%Y%m%d%H%M%S")
    df = df.drop(columns=["date", "time"])  # 합쳤으니 원본 두 컬럼은 제거

    # 최종 컬럼 순서 정리.
    cols = ["code", "datetime", "open", "high", "low", "close", "volume"]
    df = df[cols]

    # CSV 저장 (utf-8-sig: 엑셀에서 한글이 깨지지 않도록 BOM 포함).
    out_path = f"./data/minute_chart_{STOCK_CODE}.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(f"\n총 {len(df)}건 → {out_path}")
    print(df.head())  # 결과 앞 3줄 미리보기


if __name__ == "__main__":
    main()
