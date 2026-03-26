"""
해외선물 종목코드 마스터 조회
- 한국투자증권 해외선물 마스터(ffcode.mst) 파일을 다운로드하여 종목정보를 조회합니다.
"""

import os
import ssl
import urllib.request
import zipfile

import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def get_overseas_future_master():
    """해외선물 마스터 파일(ffcode.mst)을 다운로드하여 DataFrame으로 반환"""
    ssl._create_default_https_context = ssl._create_unverified_context

    zip_path = os.path.join(BASE_DIR, "ffcode.mst.zip")
    mst_path = os.path.join(BASE_DIR, "ffcode.mst")

    print("해외선물 종목코드 마스터 다운로드 중...")
    urllib.request.urlretrieve(
        "https://new.real.download.dws.co.kr/common/master/ffcode.mst.zip",
        zip_path,
    )

    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(BASE_DIR)

    columns = [
        '종목코드',
        '서버자동주문 가능 종목 여부',
        '서버자동주문 TWAP 가능 종목 여부',
        '서버자동 경제지표 주문 가능 종목 여부',
        '필러',
        '종목한글명',
        '거래소코드',
        '품목코드',
        '품목종류',
        '출력 소수점',
        '계산 소수점',
        '틱사이즈',
        '틱가치',
        '계약크기',
        '가격표시진법',
        '환산승수',
        '최다월물여부',
        '최근월물여부',
        '스프레드여부',
        '스프레드기준종목 LEG1 여부',
        '서브 거래소 코드',
    ]

    rows = []
    with open(mst_path, mode="r", encoding="cp949") as f:
        for row in f:
            rows.append([
                row[:32],                # 종목코드
                row[32:33].rstrip(),     # 서버자동주문 가능 종목 여부
                row[33:34].rstrip(),     # 서버자동주문 TWAP 가능 종목 여부
                row[34:35],              # 서버자동 경제지표 주문 가능 종목 여부
                row[35:82].rstrip(),     # 필러
                row[82:107].rstrip(),    # 종목한글명
                row[-92:-82],            # 거래소코드 (ISAM KEY 1)
                row[-82:-72].rstrip(),   # 품목코드 (ISAM KEY 2)
                row[-72:-69].rstrip(),   # 품목종류
                row[-69:-64],            # 출력 소수점
                row[-64:-59].rstrip(),   # 계산 소수점
                row[-59:-45].rstrip(),   # 틱사이즈
                row[-45:-31],            # 틱가치
                row[-31:-21].rstrip(),   # 계약크기
                row[-21:-17].rstrip(),   # 가격표시진법
                row[-17:-7],             # 환산승수
                row[-7:-6].rstrip(),     # 최다월물여부 0:원월물 1:최다월물
                row[-6:-5].rstrip(),     # 최근월물여부 0:원월물 1:최근월물
                row[-5:-4].rstrip(),     # 스프레드여부
                row[-4:-3].rstrip(),     # 스프레드기준종목 LEG1 여부
                row[-3:].rstrip(),       # 서브 거래소 코드
            ])

    df = pd.DataFrame(rows, columns=columns)

    # 임시파일 정리
    os.remove(zip_path)
    os.remove(mst_path)

    return df


def get_most_traded(product_code: str):
    """지정한 품목코드의 최다월물 종목코드를 반환

    Args:
        product_code: 품목코드 (예: 'ES', 'BRN', 'GX', 'HSI' 등)

    Returns:
        dict: {'code': 'BRNK26', 'name': 'Brent Crude-202605'} 또는 None
    """
    df = get_overseas_future_master()
    matched = df[(df['품목코드'].str.strip() == product_code) & (df['최다월물여부'] == '1')]

    if len(matched) == 0:
        print(f"품목코드 '{product_code}' 최다월물을 찾을 수 없습니다.")
        return None

    row = matched.iloc[0]
    code = row['종목코드'].strip()
    name = row['종목한글명'].strip()
    print(f"최다월물: {code} ({name})")
    return {'code': code, 'name': name}


if __name__ == "__main__":
    get_most_traded("BRN")
