# 자사주 취득 공시 전후 분봉 가격 데이터 수집 과제

## 과제 소개

이번 과제에서는 앞선 과제에서 완성한 `report_final.csv`(자사주 취득 공시 목록)를 입력으로 받아,
**각 공시 시점 전후의 1분봉 가격 데이터**를 한국투자증권(KIS) Open API로 수집하여 `data/price.csv`를 완성하는 파이프라인을 구축합니다.

공시가 발생한 분을 기준 시점 **t** 라고 할 때, **t 부터 t 직후 1000개 봉**(t 봉 포함)을 수집합니다.

---

## 전체 흐름

```
[입력] data/report_final.csv  (이전 과제 결과물)
         ↓
[1단계] preprocess.py 직접 작성
    → report_final.csv 정제 (휴장일 공시 제거 + 장중 공시만 필터링)
         ↓
[2단계] kis_auth.py 직접 작성 (KIS 인증·토큰 관리)
    → config/token_cache.json 생성 (접근 토큰 캐시)
         ↓
[3단계] get_price.py 직접 작성 (KIS 분봉 조회)
    → data/price.csv 생성 (공시 전후 분봉 가격)
```

---

## 사전 준비

### 1. KIS Open API 키 발급

[한국투자증권 KIS Developers](https://apiportal.koreainvestment.com/)에서 회원가입 후 API KEY (**APP KEY / APP SECRET)**를 발급받습니다. (실전투자 계좌 기준) 프로젝트 루트에 `.env` 파일을 생성하고 아래 형식으로 입력합니다.

```
KIS_APP_KEY=발급받은_APP_KEY
KIS_APP_SECRET=발급받은_APP_SECRET
```

### 2. 패키지 설치

`requests`, `pandas`, `python-dotenv`, `exchange_calendars` 패키지를 설치합니다.

### 3. 데이터 폴더 확인

프로젝트 루트에 `data` 폴더가 있고, 그 안에 이전 과제 결과물인 `report_final.csv`를 복사 붙여넣기 합니다.

---

## 실행 순서

> **1~3단계 코드를 직접 작성**하세요. 반드시 순서대로 실행해야 합니다.

---

## 1단계: 공시 데이터 전처리 — `preprocess.py` (직접 작성)

### 작성 목표

`report_final.csv`에서 분봉 수집이 가능한 공시만 남기도록 정제합니다.
**휴장일(주말·공휴일)에 찍힌 공시를 제거**하고, **평일 장중(09:00 ~ 15:20) 공시만** 남긴 뒤 `data/report_final.csv`를 덮어씁니다.

### 구현 단계

**① 파일 읽기**

`report_final.csv`를 읽습니다. 이때 `stock_code`는 앞자리 0이 사라지지 않도록 **문자열(str)로 읽고** 6자리로 맞춥니다(`zfill(6)`). `datetime` 컬럼은 `pd.to_datetime`으로 날짜·시각 타입으로 변환합니다.

**② 거래일(세션) 집합 만들기 (전처리)**

`exchange_calendars`로 한국거래소(`XKRX`) 달력을 가져옵니다.
`datetime`의 **최소~최대 날짜 범위**에 대한 세션(거래일) 목록을 구해 `YYYYMMDD` 문자열 **집합(set)** 으로 만드세요.

> XKRX 세션은 주말과 공휴일을 모두 제외한 **실제 개장일**이므로, 이 한 번으로 주말 필터까지 같이 해결됩니다. 별도의 요일 필터는 필요 없습니다.

```python
import exchange_calendars as xcals

_dt = pd.to_datetime(df["datetime"])

_xkrx = xcals.get_calendar("XKRX")
_sessions = set(
    _xkrx.sessions_in_range(
        _dt.min().normalize(), _dt.max().normalize()
    ).strftime("%Y%m%d")
)
```

**③ 거래일 + 장중 시간 필터 만들기 (전처리)**

두 조건을 각각 불리언(boolean) 마스크로 만든 뒤 결합합니다.

- **거래일 여부**: 각 행 날짜(`YYYYMMDD`)가 ②의 세션 집합에 포함되는가
- **장중 여부**: 시각을 **분 단위로 환산**(`시*60 + 분`)했을 때 09:00 초과 ~ 15:20 미만인가

```python
_is_trading_day = _dt.dt.strftime("%Y%m%d").isin(_sessions)

_minutes = _dt.dt.hour * 60 + _dt.dt.minute
_in_session = (_minutes > 9 * 60) & (_minutes < 15 * 60 + 20)
```

**④ 필터 적용 및 저장**

두 조건을 모두 만족하는 행만 남겨(`df[_is_trading_day & _in_session]`) `data/report_final.csv`를 덮어씁니다.

### 완성 확인

저장 후 **전처리 전/후 행 수**를 출력해 휴장일·장외 공시가 제거되었는지 확인합니다.

---

## 2단계: KIS 인증 모듈 — `kis_auth.py` (직접 작성)

### 작성 목표

KIS Open API 호출에 필요한 **접근 토큰(access token)을 발급·캐싱**하고, 인증 헤더를 만들어 주는 모듈을 작성합니다.
이 모듈은 3단계에서 모든 API 호출에 재사용됩니다.

### API 명세

API 개발가이드 (접근토큰 발급): [https://apiportal.koreainvestment.com/apiservice](https://apiportal.koreainvestment.com/apiservice) (OAuth 인증 > Hashkey/접근토큰)

- 엔드포인트: `POST https://openapi.koreainvestment.com:9443/oauth2/tokenP`
- 요청 본문: `grant_type=client_credentials`, `appkey`, `appsecret`
- 응답: `access_token`, `expires_in`, `access_token_token_expired`(만료시각)

### 구현 단계

**① 라이브러리 임포트 및 키 로드**

`os`, `json`, `requests`, `datetime`, `dotenv`를 임포트합니다. `load_dotenv()`로 `.env`를 로드한 뒤 `os.environ`에서 `KIS_APP_KEY`, `KIS_APP_SECRET`을 가져옵니다.

**② 토큰 캐싱 (중요)**

토큰 발급 API는 호출 횟수 제한이 엄격합니다(분당 1회 수준). 발급받은 토큰을 `config/token_cache.json`에 저장하고, **만료 전이면 캐시를 재사용**하세요.

- 캐시 파일이 있고 `access_token_token_expired`(만료시각)가 현재 시각보다 미래이면 → 캐시된 토큰 사용
- 그렇지 않으면 → 새로 발급 후 캐시 저장

**③ 토큰 발급 함수**

캐시가 유효하면 그대로 반환하고, 아니면 `tokenP` 엔드포인트를 호출해 발급받은 뒤 캐시에 저장하는 함수를 작성합니다.

**④ 인증 헤더 생성 함수**

다른 모듈에서 가져다 쓸 수 있도록, `Authorization: Bearer {access_token}`, `appkey`, `appsecret`, `Content-Type`을 담은 헤더 dict를 반환하는 함수를 작성합니다.

### 완성 확인

모듈을 단독 실행했을 때 토큰이 정상 발급되고, **재실행 시 캐시가 재사용**되어 새로 발급하지 않으면 성공입니다.

---

## 3단계: 공시 전후 분봉 수집 — `get_price.py` (직접 작성)

### 작성 목표

정제된 `report_final.csv`의 각 행 `(datetime, stock_code)`에 대해,
공시 분(分)을 t 로 보고 **t 부터 t 직후 1000개 봉**(t 봉 포함)의 1분봉을 조회하여
`data/price.csv`로 저장합니다.

### API 명세

API 개발가이드 (국내주식 일별분봉조회): [https://apiportal.koreainvestment.com/apiservice](https://apiportal.koreainvestment.com/apiservice)

- 엔드포인트: `GET /uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice`
- `tr_id`: `FHKST03010230`, `custtype`: `P`

**요청 파라미터**


| 파라미터                     | 값          | 설명                              |
| ------------------------ | ---------- | ------------------------------- |
| `FID_COND_MRKT_DIV_CODE` | `J`        | 시장 구분(주식)                       |
| `FID_INPUT_ISCD`         | 종목코드       | 6자리 종목코드                        |
| `FID_INPUT_DATE_1`       | `YYYYMMDD` | 조회 기준일                          |
| `FID_INPUT_HOUR_1`       | `HHMMSS`   | 조회 기준시각 (이 시각부터 **과거 방향**으로 반환) |
| `FID_PW_DATA_INCU_YN`    | `Y`        | 과거 데이터 포함                       |
| `FID_FAKE_TICK_INCU_YN`  | `""`       | 허봉 포함 여부                        |


**응답 필드 매핑 (`output2` 배열의 각 원소)**


| 결과 컬럼      | 원본키                                 | 설명                     |
| ---------- | ----------------------------------- | ---------------------- |
| `datetime` | `stck_bsop_date` + `stck_cntg_hour` | 영업일자 + 체결시각(HHMMSS) 결합 |
| `open`     | `stck_oprc`                         | 시가                     |
| `high`     | `stck_hgpr`                         | 고가                     |
| `low`      | `stck_lwpr`                         | 저가                     |
| `close`    | `stck_prpr`                         | 종가(현재가)                |
| `volume`   | `cntg_vol`                          | 거래량                    |


### 구현 단계

**① 인증 헤더 준비**

2단계의 `kis_auth`에서 인증 헤더를 가져오고, `tr_id`(`FHKST03010230`)와 `custtype`(`P`)을 추가합니다.

**② 하루치 분봉 수집 (역방향 커서)**

이 API는 **한 번 호출에 기준시각부터 과거 방향으로 일정 개수(약 100여 건)만** 반환합니다.
하루(09:00~15:30) 전체를 받으려면, 응답에서 **가장 이른 체결시각**을 찾아 거기서 1분을 뺀 시각으로 다시 조회하는 식으로 **커서를 거꾸로 이동하며 반복 호출**합니다. 장 시작(09:00)에 도달하면 멈춥니다.

> 같은 체결시각이 중복 수신될 수 있으므로, 이미 받은 시각은 집합(set)으로 관리해 **중복을 제거**하세요.
>
> ⚠️ **무한 루프 주의 (중요)**: 거래가 희소한 종목은 그날 **첫 체결이 09:00보다 늦을 수** 있습니다(예: 09:02 첫 체결, 09:00 동시호가 캔들 없음). 이 경우 "09:00에 도달하면 멈춤" 조건만으로는 `earliest`가 더 내려가지 않아 같은 데이터를 무한 반복 수신합니다. **직전 `earliest`보다 더 작아지지 않으면(=진전이 없으면) 즉시 중단**하는 안전장치를 반드시 넣으세요.

**③ 봉 개수 기준 수집 (핵심)**

기준 시점 t 부터, **벽시계 시간이 아니라 거래 분봉 '개수'** 기준으로 모읍니다. 야간·휴장 갭은 건너뛰고 다음 거래일로 이어서 셉니다.

- **정방향**: t 이후 봉이 **1000개**가 될 때까지, t의 거래일부터 시작해 **다음 거래일**로 진행하며 장 전체를 수집
- 무한 루프 방지를 위해 거래일 탐색 횟수에 **안전 한도**를 둡니다.

**④ 봉 잘라내기**

수집한 봉을 시각 오름차순으로 정렬한 뒤 다음을 이어 붙입니다.

- t 와 **정확히 일치하는 봉**(있으면 1개)
- t 이후 봉 중 **앞 1000개**

> t 시점에 실제 분봉이 있으면 1001개, 없으면(거래 공백 등) 1000개가 됩니다. 1단계 전처리로 장중 공시만 남겼으므로 대부분 1001개가 됩니다.

**⑤ API 속도 제한 (중요)**

KIS는 **초당 호출 수 제한**(실전계좌 기준)이 있습니다. 최근 1초간의 호출 시각을 기록하는 **슬라이딩 윈도우** 방식으로 초당 호출 수를 한도 이하(예: 10회)로 유지하고, 초과 시 `time.sleep`으로 대기하세요. 속도 제한 카운터는 행이 바뀌어도 초기화되지 않도록 **전체 실행에서 공유**합니다.

**⑥ 후처리 — 정상 공시만 남기기 (중요)**

수집 과정에서 봉이 온전히 채워지지 않거나 장 마감 이후 봉이 섞여 들어오는 공시가 생깁니다.
아래 **3조건을 모두 만족하는 공시("정상 공시")만** 남기고, 하나라도 어긋나는 공시는
`price.csv`에 담지 않고 `report_final.csv`에서도 삭제(덮어쓰기)합니다.

| 조건 | 설명 |
| ---- | ---- |
| ① t봉 존재 | 공시 시각 t 의 분봉이 실제로 있어야 함 |
| ② 정확히 1001봉 | t봉 1개 + t 이후 1000봉 |
| ③ 전부 정규장 | 모든 봉이 09:00 ~ 15:30 범위 (시간외 봉 배제) |

> **왜 필요한가?**
> - **t봉 없음**: 거래가 희소해 t 분에 체결이 없거나, KIS가 최근 약 1년치 분봉만 제공해
>   공시일 데이터가 아예 없는 경우가 있습니다. (t봉은 허봉 포함 옵션으로도 복구되지 않습니다.)
> - **시간외 봉 혼입**: KIS 분봉 API는 15:30 으로 조회해도 **간헐적으로 시간외(15:30 이후,
>   최대 18:00)** 봉을 함께 반환합니다. 이 봉이 창에 섞이면 정규장 봉이 그만큼 밀려나
>   1001봉의 구성이 어긋납니다.
>
> 제외는 **공시 건(종목 + t) 단위**로 합니다. 같은 종목의 다른 정상 공시는 그대로 유지합니다.
> 제외 시 사유(`t봉 없음` / `봉 수 부족` / `시간외 봉 포함`)를 함께 출력하면 확인하기 좋습니다.

**⑦ 결과 결합 및 저장**

정상 공시들의 결과를 합쳐 아래 컬럼 순서의 DataFrame으로 만들고 `data/price.csv`로 저장합니다.
가격·거래량 컬럼은 숫자형으로 변환하세요.

### 최종 데이터프레임 컬럼


| 컬럼           | 설명         |
| ------------ | ---------- |
| `stock_code` | 종목코드 (6자리) |
| `datetime`   | 분봉 날짜 시간   |
| `open`       | 시가         |
| `high`       | 고가         |
| `low`        | 저가         |
| `close`      | 종가         |
| `volume`     | 거래량        |


### 완성 확인

`data/price.csv`가 생성되고, **남은 모든 공시가 정확히 1001개**의 분봉을 갖고 있으면 성공입니다. 봉이 전부 정규장(09:00~15:30) 범위인지, 시간외(15:30 초과) 봉이 0건인지, `price.csv`와 후처리로 갱신된 `report_final.csv`의 공시 수가 일치하는지 확인합니다.

---

## 전체 실행 체크리스트

- [ ] `.env`에 `KIS_APP_KEY`, `KIS_APP_SECRET` 입력
- [ ] `data/report_final.csv`(이전 과제 결과물) 복사 붙여넣기
- [ ] `preprocess.py` 작성 후 실행 → 휴장일·장외 공시 제거 확인
- [ ] `kis_auth.py` 작성 후 실행 → 토큰 발급·캐시 확인
- [ ] `get_price.py` 작성 후 실행 → `data/price.csv` 생성 확인

---

## 최종 결과물

- `preprocess.py`
- `kis_auth.py`
- `get_price.py`
- `data/price.csv`

