from __future__ import annotations

import httpx

CLUSTER_API = "https://cynosdb.cloud.tencent.com/api/cloud3/cynosdb/DescribeClusters"
DEFAULT_REGION = "ap-shanghai"
DEFAULT_LIMIT = 100


def search_cluster_by_ip(cookie: str, ip: str, region: str = DEFAULT_REGION) -> list[dict]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Cookie": cookie,
        "Origin": "https://console.cloud.tencent.com",
        "Referer": "https://console.cloud.tencent.com/cynosdb/mysql/ap-shanghai/cluster",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/149.0.0.0 Safari/537.36"
        ),
        "X-Requested-With": "XMLHttpRequest",
    }

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
            "NetAddrs": [
                {"NetType": a.get("NetType", ""), "Vip": a.get("Vip", ""), "Vport": a.get("Vport", 3306)}
                for a in c.get("NetAddrs", [])
            ],
        }
        for c in matched
    ]
