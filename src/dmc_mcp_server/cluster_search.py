from __future__ import annotations

import os
import httpx

for _k in ("ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "http_proxy", "https_proxy"):
    os.environ.pop(_k, None)
os.environ.setdefault("NO_PROXY", "*")

CLUSTER_API = "https://cynosdb.cloud.tencent.com/api/cloud3/cynosdb/DescribeClusters"
TDSQL_API = "https://tdsql.cloud.tencent.com/api/cloud3/tdsql/DescribeDCDBInstances"
DEFAULT_REGION = "ap-shanghai"
DEFAULT_LIMIT = 100

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/149.0.0.0 Safari/537.36"
)


def _base_headers(cookie: str) -> dict:
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Cookie": cookie,
        "User-Agent": _UA,
        "X-Requested-With": "XMLHttpRequest",
    }


def search_cluster_by_ip(
    cookie: str, ip: str, mc_gtk: int = 0, region: str = DEFAULT_REGION
) -> list[dict]:
    """Search TDSQL-C (CynosDB) clusters by internal Vip."""
    headers = _base_headers(cookie)
    headers["Origin"] = "https://console.cloud.tencent.com"
    headers["Referer"] = "https://console.cloud.tencent.com/cynosdb/mysql/ap-shanghai/cluster"

    body = {
        "Offset": 0,
        "Limit": DEFAULT_LIMIT,
        "DbType": "MYSQL",
        "Filters": [
            {
                "Names": ["Status"],
                "Values": ["creating", "running", "isolating", "processing"],
                "ExactMatch": True,
            }
        ],
        "Region": region,
    }
    if mc_gtk:
        body["mc_gtk"] = mc_gtk

    with httpx.Client(trust_env=False, timeout=15) as client:
        resp = client.post(CLUSTER_API, json=body, headers=headers)

    data = resp.json()
    clusters = data.get("data", {}).get("ClusterSet", [])

    matched = []
    for c in clusters:
        if c.get("Vip") == ip:
            matched.append(c)
            continue
        for addr in c.get("NetAddrs", []):
            if addr.get("Vip") == ip:
                matched.append(c)
                break

    return [
        {
            "ClusterId": c.get("ClusterId", ""),
            "ClusterName": c.get("ClusterName", ""),
            "Vip": c.get("Vip", ""),
            "DbType": "cynosdbmysql",
            "NetAddrs": [
                {"NetType": a.get("NetType", ""), "Vip": a.get("Vip", ""), "Vport": a.get("Vport", 3306)}
                for a in c.get("NetAddrs", [])
            ],
        }
        for c in matched
    ]


def search_tdsql_by_ip(
    cookie: str, ip: str, mc_gtk: int = 0, region: str = DEFAULT_REGION
) -> list[dict]:
    """Search TDSQL (DCDB) instances by Vip via server-side SearchKey."""
    headers = _base_headers(cookie)
    headers["Origin"] = "https://console.cloud.tencent.com"
    headers["Referer"] = "https://console.cloud.tencent.com/tdsqld/instance-tdmysql"
    if mc_gtk:
        headers["X-Csrfcode"] = str(mc_gtk)

    body = {
        "Region": region,
        "Offset": 0,
        "Limit": DEFAULT_LIMIT,
        "SearchName": "all",
        "SearchKey": f"\n{ip}",
        "ExcludeStatus": [-1],
        "OrderBy": "createtime",
        "OrderByType": "desc",
    }

    with httpx.Client(trust_env=False, timeout=15) as client:
        resp = client.post(TDSQL_API, json=body, headers=headers)

    data = resp.json()
    instances = data.get("data", {}).get("Instances", [])
    return [
        {
            "ClusterId": inst.get("InstanceId", ""),
            "ClusterName": inst.get("InstanceName", ""),
            "Vip": inst.get("Vip", ""),
            "Vport": inst.get("Vport", 3306),
            "DbType": "tdsql",
            "ShardCount": inst.get("ShardCount", 0),
            "Status": inst.get("StatusDesc", ""),
            "Zone": inst.get("Zone", ""),
        }
        for inst in instances
        if inst.get("Vip") == ip
    ]


def search_all_by_ip(
    cookie: str, ip: str, mc_gtk: int = 0, region: str = DEFAULT_REGION
) -> list[dict]:
    """Search both TDSQL-C and TDSQL instances by IP."""
    results: list[dict] = []
    try:
        results.extend(search_cluster_by_ip(cookie, ip, mc_gtk, region))
    except Exception:
        pass
    try:
        results.extend(search_tdsql_by_ip(cookie, ip, mc_gtk, region))
    except Exception:
        pass
    return results
