"""코스피/코스닥 종목마스터를 KIS 제공 mst 파일에서 받아 정제하여
stock_master.csv 로 저장한다.

- KIS 는 종목 기본정보를 고정폭(fixed-width) 텍스트인 *.mst 파일로 배포한다.
  (kospi_code.mst / kosdaq_code.mst, cp949 인코딩, zip 압축)
- 각 행 앞부분에 단축코드(9) · 표준코드(12) · 한글종목명 이 들어있고,
  뒤쪽 고정폭 구간은 이 스크립트에서 필요치 않아 잘라낸다.
  (코스피는 뒤 228바이트, 코스닥은 뒤 222바이트가 상세정보 구간)
- 결과 컬럼: 단축코드, 표준코드, 한글종목명, 소속시장
"""

import os
import ssl
import zipfile
import tempfile
import urllib.request
import pandas as pd

OUT_PATH = "./data/stock_master.csv"

# (시장명, 다운로드 URL, mst 파일명, 뒤쪽 상세구간 바이트 길이)
MARKETS = [
    ("코스피", "https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip",
     "kospi_code.mst", 228),
    ("코스닥", "https://new.real.download.dws.co.kr/common/master/kosdaq_code.mst.zip",
     "kosdaq_code.mst", 222),
]

COLS = ["stock_code", "isin_code", "stock_name", "market"]


def download_mst(url: str, mst_name: str, work_dir: str) -> str:
    """zip 을 내려받아 work_dir 에 풀고, 추출된 mst 파일 경로를 반환한다."""
    # KIS 배포 서버 인증서 검증을 생략(레퍼런스 코드와 동일 동작).
    ssl._create_default_https_context = ssl._create_unverified_context

    zip_path = os.path.join(work_dir, mst_name + ".zip")
    urllib.request.urlretrieve(url, zip_path)

    with zipfile.ZipFile(zip_path) as z:
        z.extractall(work_dir)
    os.remove(zip_path)

    return os.path.join(work_dir, mst_name)


def parse_master(mst_path: str, market: str, tail_len: int) -> pd.DataFrame:
    """mst 파일에서 단축코드/표준코드/한글종목명 을 뽑아 DataFrame 으로 반환."""
    rows = []
    with open(mst_path, mode="r", encoding="cp949") as f:
        for row in f:
            head = row[0:len(row) - tail_len]     # 뒤 상세구간을 잘라낸 앞부분
            short_code = head[0:9].rstrip()       # 단축코드
            std_code   = head[9:21].rstrip()      # 표준코드
            name       = head[21:].strip()        # 한글종목명
            rows.append((short_code, std_code, name, market))

    return pd.DataFrame(rows, columns=COLS)


def main():
    frames = []
    with tempfile.TemporaryDirectory() as work_dir:
        for market, url, mst_name, tail_len in MARKETS:
            print(f"{market} 종목마스터 다운로드/파싱 중...", end=" ", flush=True)
            mst_path = download_mst(url, mst_name, work_dir)
            df = parse_master(mst_path, market, tail_len)
            frames.append(df)
            print(f"{len(df)}건")

    result = pd.concat(frames, ignore_index=True)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    result.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")

    print(f"\n총 {len(result)}건 → {OUT_PATH}")
    print(result.head(10).to_string())


if __name__ == "__main__":
    main()
