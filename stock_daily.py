import json
import requests
from kis_auth import get_auth_headers, BASE_URL

params = {
    "FID_COND_MRKT_DIV_CODE": "J",
    "FID_INPUT_ISCD":         "005930",
    "FID_INPUT_DATE_1":       "20260528",
    "FID_INPUT_DATE_2":       "20260601",
    "FID_PERIOD_DIV_CODE":    "D",
    "FID_ORG_ADJ_PRC":        "0",
}

headers = get_auth_headers()
headers["tr_id"]    = "FHKST03010100"
headers["custtype"] = "P"

resp = requests.get(
    f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
    headers=headers,
    params=params,
    timeout=10,
)
resp.raise_for_status()

print("\n=== Response Body ===")
print(json.dumps(resp.json(), ensure_ascii=False, indent=2))
