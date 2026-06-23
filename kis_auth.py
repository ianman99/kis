"""KIS Open API 인증 모듈.

한국투자증권(KIS) Open API 호출에 필요한 접근 토큰(access token)을
발급·캐싱하고, 인증 헤더를 만들어 주는 모듈이다.
다른 모듈(get_price.py 등)에서 import 해서 재사용한다.

토큰 발급 API는 호출 횟수 제한(분당 1회 수준)이 엄격하므로,
한 번 발급받은 토큰은 config/token_cache.json 에 저장해 두고
만료 전까지 재사용한다.
"""

import os
import json
import requests
from datetime import datetime
from dotenv import load_dotenv

# .env 파일을 읽어 환경변수로 로드한다 (KIS_APP_KEY, KIS_APP_SECRET).
load_dotenv()

# 발급받은 API 키와 호출 기본 주소. .env 에 키가 없으면 여기서 즉시 에러난다.
APP_KEY    = os.environ["KIS_APP_KEY"]
APP_SECRET = os.environ["KIS_APP_SECRET"]
BASE_URL   = "https://openapi.koreainvestment.com:9443"

# 토큰 캐시 파일 경로. 이 소스파일과 같은 폴더의 config/token_cache.json 에 저장한다.
_CACHE_DIR  = os.path.join(os.path.dirname(__file__), "config")
_CACHE_FILE = os.path.join(_CACHE_DIR, "token_cache.json")


def _load_cache() -> dict | None:
    """캐시된 토큰을 읽어 아직 유효하면 반환, 아니면 None.

    파일이 없거나 / 형식이 깨졌거나 / 이미 만료됐으면 None 을 돌려
    호출 측이 새로 발급하도록 한다.
    """
    try:
        with open(_CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        # 만료시각 문자열을 datetime 으로 변환. 형식 예: "2026-06-02 11:23:45"
        expired_at = datetime.strptime(data["access_token_token_expired"], "%Y-%m-%d %H:%M:%S")
        # 현재 시각이 만료시각보다 이전이면(=아직 안 만료) 캐시 사용.
        if datetime.now() < expired_at:
            return data
    except (FileNotFoundError, KeyError, ValueError):
        # 파일 없음 / 필요한 키 없음 / 날짜 파싱 실패 → 캐시 무효로 간주.
        pass
    return None


def _save_cache(data: dict) -> None:
    """발급받은 토큰 응답(dict)을 캐시 파일에 JSON 으로 저장한다."""
    with open(_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_access_token() -> dict:
    """접근 토큰을 반환한다. 유효한 캐시가 있으면 재사용, 없으면 새로 발급.

    반환값은 access_token, token_type, expires_in,
    access_token_token_expired 등을 담은 응답 dict 이다.
    """
    # 1) 캐시에 유효한 토큰이 있으면 API 호출 없이 그대로 반환.
    cached = _load_cache()
    if cached:
        return cached

    # 2) 없으면 tokenP 엔드포인트로 새 토큰을 발급받는다.
    resp = requests.post(
        f"{BASE_URL}/oauth2/tokenP",
        headers={"Content-Type": "application/json; charset=UTF-8"},
        json={
            "grant_type": "client_credentials",  # OAuth2 클라이언트 자격증명 방식
            "appkey":     APP_KEY,
            "appsecret":  APP_SECRET,
        },
        timeout=10,
    )
    resp.raise_for_status()  # HTTP 에러(4xx/5xx)면 예외 발생.
    data = resp.json()
    # 3) 새로 받은 토큰을 캐시에 저장해 다음 실행 때 재사용하도록 한다.
    _save_cache(data)
    return data


def get_auth_headers() -> dict:
    """KIS API 호출에 공통으로 들어가는 인증 헤더 dict 를 만들어 반환한다.

    개별 API 모듈은 여기에 tr_id, custtype 등을 추가해서 사용한다.
    """
    return {
        "Authorization": f"Bearer {get_access_token()['access_token']}",
        "appkey":        APP_KEY,
        "appsecret":     APP_SECRET,
        "Content-Type":  "application/json; charset=UTF-8",
    }


if __name__ == "__main__":
    # 모듈을 단독 실행하면 토큰 발급/캐시가 정상 동작하는지 확인한다.
    # 첫 실행은 새로 발급, 재실행 시 만료 전이면 캐시를 재사용한다.
    data = get_access_token()
    print(f"access_token  : {data['access_token'][:10]}...")  # 토큰 앞 10자만 노출.
    print(f"token_type    : {data['token_type']}")
    print(f"expires_in    : {data['expires_in']}")
    print(f"token_expired : {data['access_token_token_expired']}")
