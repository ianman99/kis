"""
지수선물 종목코드 마스터 조회
- KOSPI200 선물, KOSDAQ150 선물의 현재 활성 종목코드를 확인합니다.
"""

import os
import ssl
import urllib.request
import zipfile
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def get_index_future_codes():
    """지수선물옵션 마스터 파일을 다운로드하여 DataFrame으로 반환"""
    ssl._create_default_https_context = ssl._create_unverified_context

    zip_path = os.path.join(BASE_DIR, "fo_idx_code_mts.mst.zip")
    mst_path = os.path.join(BASE_DIR, "fo_idx_code_mts.mst")

    print("종목코드 마스터 다운로드 중...")
    urllib.request.urlretrieve(
        "https://new.real.download.dws.co.kr/common/master/fo_idx_code_mts.mst.zip",
        zip_path
    )

    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(BASE_DIR)

    columns = ['상품종류', '단축코드', '표준코드', '한글종목명', 'ATM구분',
               '행사가', '월물구분코드', '기초자산단축코드', '기초자산명']
    df = pd.read_table(mst_path, sep='|', encoding='cp949', header=None)
    df.columns = columns

    # 임시파일 정리
    os.remove(zip_path)
    os.remove(mst_path)

    return df


def get_cme_night_codes():
    """CME연계 야간선물 마스터(fo_cme_code.mst) 다운로드 후 DataFrame 반환
    고정폭 파싱: 상품종류[1] 단축코드[9] 표준코드[12] 한글종목명[41] 행사가[9] 기초자산단축코드[9] 기초자산명[~]
    """
    ssl._create_default_https_context = ssl._create_unverified_context

    zip_path = os.path.join(BASE_DIR, "fo_cme_code.mst.zip")
    mst_path = os.path.join(BASE_DIR, "fo_cme_code.mst")

    urllib.request.urlretrieve(
        "https://new.real.download.dws.co.kr/common/master/fo_cme_code.mst.zip",
        zip_path
    )
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(BASE_DIR)

    columns = ['상품종류', '단축코드', '표준코드', '한글종목명', '행사가', '기초자산단축코드', '기초자산명']
    rows = []
    with open(mst_path, mode='r', encoding='cp949') as f:
        for row in f:
            rows.append([
                row[0:1],
                row[1:10].strip(),
                row[10:22].strip(),
                row[22:63].strip(),
                row[63:72].strip(),
                row[72:81].strip(),
                row[81:].strip(),
            ])
    df = pd.DataFrame(rows, columns=columns)

    os.remove(zip_path)
    os.remove(mst_path)
    return df


def get_nearest_codes() -> dict:
    """KOSPI200, KOSDAQ150 최근월물 + KOSPI200 야간선물 최근월물 코드를 자동으로 반환

    Returns:
        {'KOSPI200': {'code': 'A01603', 'name': 'F 202603'},
         'KOSDAQ150': {'code': 'A06603', 'name': '코스닥150F 202603'},
         'KOSPI200_NIGHT': {'code': 'A01603', 'name': 'F 202603'}}
    """
    # 주간 지수선물
    df = get_index_future_codes()
    result = {}
    targets = {'1': 'KOSPI200', '3': 'KOSDAQ150'}
    for type_code, label in targets.items():
        row = df[(df['상품종류'] == type_code) & (df['월물구분코드'] == '1')]
        if len(row) > 0:
            r = row.iloc[0]
            result[label] = {'code': r['단축코드'], 'name': r['한글종목명'].strip()}

    # CME 야간선물 (상품종류 '1' = 야간선물, 행사가 순서로 최근월물 판별)
    ngt = get_cme_night_codes()
    ngt_futures = ngt[ngt['상품종류'] == '1'].sort_values('행사가')
    if len(ngt_futures) > 0:
        r = ngt_futures.iloc[0]
        result['KOSPI200_NIGHT'] = {'code': r['단축코드'], 'name': r['한글종목명'].strip()}

    return result


def show_futures_codes():
    """KOSPI200, KOSDAQ150 선물 종목코드 표시"""
    df = get_index_future_codes()

    # 상품종류 (info_type[1]) - ST_FO_IDX_CODE 구조체 기준
    # 선물: 1=지수선물, 3=스타(KOSDAQ150)선물, 7=변동성선물, 9=섹터선물, B=미니선물, H=KRX300선물
    # SP:   2=지수SP,   4=스타SP,             8=변동성SP,   A=섹터SP,   C=미니SP,   I=KRX300SP
    # 옵션: 5=지수콜,   6=지수풋,  D=미니콜,  E=미니풋,  J=코스닥150콜,  K=코스닥150풋
    #        L=위클리콜, M=위클리풋, N=위클리M콜, O=위클리M풋, R=코스닥위클리M콜, S=코스닥위클리M풋
    # 월물구분코드 (mmsc_cls_code[1]): 0=연결선물, 1=최근월물, 2=차근월물, 3=차차근월물, ...

    ALL_TYPES = {
        '1': 'KOSPI200 선물',    '2': 'KOSPI200 SP',
        '3': 'KOSDAQ150 선물',   '4': 'KOSDAQ150 SP',
        '5': 'KOSPI200 콜옵션',  '6': 'KOSPI200 풋옵션',
        '7': '변동성 선물',       '8': '변동성 SP',
        '9': '섹터 선물',         'A': '섹터 SP',
        'B': 'KOSPI200 미니선물', 'C': '미니 SP',
        'D': '미니 콜옵션',       'E': '미니 풋옵션',
        'H': 'KRX300 선물',      'I': 'KRX300 SP',
        'J': '코스닥150 콜옵션',  'K': '코스닥150 풋옵션',
        'L': '위클리 콜옵션',     'M': '위클리 풋옵션',
        'N': '위클리M 콜옵션',    'O': '위클리M 풋옵션',
        'R': '코스닥위클리M 콜',  'S': '코스닥위클리M 풋',
    }

    # 선물만 표시 (SP, 옵션 제외)
    futures_types = {
        '1': 'KOSPI200 선물',
        '3': 'KOSDAQ150 선물',
    }

    for code, name in futures_types.items():
        print(f"\n{'=' * 70}")
        print(f"  {name} (상품종류={code})")
        print("=" * 70)
        sub = df[df['상품종류'] == code].sort_values('월물구분코드')
        if len(sub) > 0:
            print(sub[['단축코드', '한글종목명', '월물구분코드']].to_string(index=False))
        else:
            print("  (데이터 없음)")

    # 최근월물만 추출하여 요약
    print("\n" + "=" * 70)
    print("  >>> 최근월물 요약 (월물구분코드=1) <<<")
    print("=" * 70)
    nearest = df[(df['월물구분코드'] == '1') & (df['상품종류'].isin(futures_types.keys()))]
    for _, row in nearest.iterrows():
        종류 = futures_types[row['상품종류']]
        print(f"  {종류:20s} | 코드: {row['단축코드']:10s} | {row['한글종목명']}")

    # CME 야간선물
    print("\n" + "=" * 70)
    print("  KOSPI200 야간선물 (CME연계, fo_cme_code.mst)")
    print("=" * 70)
    ngt = get_cme_night_codes()
    ngt_futures = ngt[ngt['상품종류'] == '1'].sort_values('행사가')
    if len(ngt_futures) > 0:
        print(ngt_futures[['단축코드', '한글종목명', '행사가']].to_string(index=False))
        r = ngt_futures.iloc[0]
        print(f"\n  >>> 야간선물 최근월물: {r['단축코드']} ({r['한글종목명']})")

    return df


if __name__ == "__main__":
    show_futures_codes()
