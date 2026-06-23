"""
해외선물옵션 장운영시간 조회 [해외선물-030]
- CME 농산물, 에너지, 금속 등 해외선물 장운영시간을 조회합니다.
- HTS [6773] 해외선물 장운영시간 화면과 동일

사용법:
    python overseas_futures_market_time.py
    python overseas_futures_market_time.py --exchange CME
    python overseas_futures_market_time.py --exchange NYMEX

사전 설정:
    config/kis_devlp.yaml 에 앱키, 앱시크릿 등 입력 필요
"""

import argparse
import logging

import pandas as pd

import kis_auth as ka

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')

# ============================================================
# API 설정
# ============================================================
API_URL = "/uapi/overseas-futureoption/v1/quotations/market-time"
TR_ID = "OTFM2229R"

# FM_EXCG_CD 거래소코드 목록
EXCHANGE_LIST = ["CME", "EUREX", "HKEx", "ICE", "SGX", "OSE", "ASX",
                 "CBOE", "MDEX", "NYSE", "BMF", "FTX", "HNX", "ETC"]

# FM_CLAS_CD 클래스코드
CLASS_NAMES = {
    "": "전체", "001": "통화", "002": "금리", "003": "지수",
    "004": "농산물", "005": "축산물", "006": "금속", "007": "에너지",
}


def fetch_market_time(fm_excg_cd: str = "CME") -> pd.DataFrame:
    """
    해외선물 장운영시간 조회

    Args:
        fm_excg_cd: FM거래소코드 (CME, EUREX, NYMEX 등)

    Returns:
        pd.DataFrame: 장운영시간 데이터
    """
    params = {
        "FM_PDGR_CD": "",
        "FM_CLAS_CD": "",
        "FM_EXCG_CD": fm_excg_cd,
        "OPT_YN": "N",
        "CTX_AREA_NK200": "",
        "CTX_AREA_FK200": "",
    }

    res = ka._url_fetch(API_URL, TR_ID, "", params)

    if not res.isOK():
        res.printError(url=API_URL)
        return pd.DataFrame()

    # 원본 JSON에서 직접 output 추출
    raw_json = res.getResponse().json()
    output = raw_json.get("output", [])

    if not output:
        return pd.DataFrame()

    # 첫 번째 항목의 키 확인 (디버그)
    print(f"[DEBUG] 응답 필드: {list(output[0].keys())}")
    print(f"[DEBUG] 샘플 데이터: {output[0]}")

    return pd.DataFrame(output)


def format_time(tmd) -> str:
    """시각 문자열(HHMMSS)을 보기 좋게 변환"""
    tmd = str(tmd).strip()
    if not tmd or len(tmd) < 4:
        return tmd or ""
    return f"{tmd[:2]}:{tmd[2:4]}"


def main():
    parser = argparse.ArgumentParser(description="해외선물 장운영시간 조회")
    parser.add_argument("--exchange", type=str, default="CME",
                        help=f"거래소코드 ({', '.join(EXCHANGE_LIST)})")
    args = parser.parse_args()

    exchange = args.exchange.upper()

    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 200)
    pd.set_option('display.max_rows', None)
    pd.set_option('display.unicode.east_asian_width', True)

    # ============================================================
    # 인증 (실전투자, 해외선물 계좌)
    # ============================================================
    ka.auth(svr="prod", product="08")

    # ============================================================
    # 장운영시간 조회
    # ============================================================
    print(f"\n{exchange} 해외선물 장운영시간을 조회합니다...")
    df = fetch_market_time(fm_excg_cd=exchange)

    if df.empty:
        print(f"{exchange} 데이터를 조회할 수 없습니다.")
        return

    # 전체 raw 데이터 출력
    print(f"\n{'=' * 90}")
    print(f"  {exchange} 해외선물 장운영시간 (전체 {len(df)}건)")
    print(f"{'=' * 90}")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
