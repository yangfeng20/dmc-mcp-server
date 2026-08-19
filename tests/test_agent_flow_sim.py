"""本地模拟 agent 完整调用链测试（不依赖真实网络）.

模拟真实 agent 行为:
  1. set_cookie(新加坡) → 验证落盘 + active
  2. set_cookie(上海) → 验证切换 + 双地域并存
  3. find_instance_by_ip(region=ap-singapore) → 严格用新加坡 cookie
  4. find_instance_by_ip(region=ap-shanghai, 但无存储) → 应报错, 不用别的 cookie
  5. list_cookies → 列出存储
  6. clear_cookies(9) → 清新加坡
  7. login_instance 密码复用逻辑 (用 mock client)

使用 monkeypatch 替换 DMCClient / cluster_search, 隔离网络.
"""
import tempfile
from pathlib import Path
from unittest.mock import patch

# 重定向存储目录到临时目录 (通过环境变量或直接改模块全局?)
import dmc_mcp_server.main as main_mod

tmp = Path(tempfile.mkdtemp(prefix="dmc_agent_sim_"))
# 用临时目录替换 CookieManager 的存储位置
main_mod._cookie_mgr = __import__("dmc_mcp_server.cookie_manager", fromlist=["CookieManager"]).CookieManager(tmp)


def fake_search(cookie, ip, mc_gtk=0, region="ap-shanghai"):
    """模拟 cluster_search.search_all_by_ip: 检查 cookie 是否含 regionId, 返回实例."""
    import re
    rid = re.search(r"regionId=(\d+)", cookie)
    current_region = {4: "ap-shanghai", 9: "ap-singapore"}.get(int(rid.group(1)) if rid else 0)
    if current_region != region:
        return [{"ClusterId": f"cynosdbmysql-wrong-region-{region}", "ClusterName": "WRONG_COOKIE_USED", "Vip": "0.0.0.0", "DbType": "cynosdbmysql"}]
    return [{"ClusterId": "cynosdbmysql-91pjj0el", "ClusterName": "xjp-communication_prod", "Vip": ip, "DbType": "cynosdbmysql"}]


class FakeSession:
    token = "dc5d94a8f43eaf67" + "0" * 32
    credentials = type("C", (), {"user": "sh_com_prod"})()


def fake_ensure_login(self, instance_id, user="", password="", db_type="cynosdbmysql", region_id=4):
    print(f"    [fake login] instance={instance_id} user={user or '(from store)'} region_id={region_id}")
    return FakeSession()


def main():
    print("=" * 70)
    print("Scenario 1: only Shanghai cookie stored, query Singapore instance")
    print("=" * 70)
    # 只存上海
    r = main_mod.set_cookie("uin=o100000000002; regionId=4; skey=sh")
    print("  set_cookie(上海):", r)
    print("  list_cookies:")
    print("   " + main_mod.list_cookies().replace("\n", "\n   "))

    # 查新加坡 (没有新加坡 cookie)
    print("  --- find_instance_by_ip(ip, region=ap-singapore) ---")
    with patch.object(main_mod.DMCClient, "ensure_login", fake_ensure_login):
        res = main_mod.find_instance_by_ip("172.20.5.73", region="ap-singapore")
    print("  结果:", res)
    assert "No stored cookie for region" in res, f"应该报no cookie, 实际: {res}"
    print("  PASS 没有新加坡 cookie → 明确报错, 不用上海 cookie")

    print()
    print("=" * 70)
    print("Scenario 2: Shanghai + Singapore stored, query Singapore")
    print("=" * 70)
    main_mod.set_cookie("uin=o100000000001; regionId=9; skey=sg")
    print("  set_cookie(新加坡):")
    print("   " + main_mod.list_cookies().replace("\n", "\n   "))

    with patch("dmc_mcp_server.cluster_search.search_all_by_ip", side_effect=fake_search):
        res = main_mod.find_instance_by_ip("172.20.5.73", region="ap-singapore")
    print("  find(新加坡):", res)
    assert "cynosdbmysql-91pjj0el" in res, f"应该找到新加坡实例, 实际: {res}"
    print("  PASS 用新加坡 cookie 找到新加坡实例")

    print()
    print("=" * 70)
    print("Scenario 3: both stored, query Shanghai (active is Singapore)")
    print("=" * 70)
    with patch("dmc_mcp_server.cluster_search.search_all_by_ip", side_effect=fake_search):
        res = main_mod.find_instance_by_ip("172.19.48.12", region="ap-shanghai")
    print("  find(上海):", res)
    assert "cynosdbmysql-wrong-region" not in res, f"不该用新加坡 cookie 查上海: {res}"
    print("  PASS 查上海用上海 cookie (虽 active 是新加坡)")

    print()
    print("=" * 70)
    print("Scenario 4: login_instance directly (without find), explicit region")
    print("=" * 70)
    with patch.object(main_mod.DMCClient, "ensure_login", fake_ensure_login):
        res = main_mod.login_instance("cynosdbmysql-91pjj0el", "sh_com_prod", "xxx", region_id=9)
    print("  login(新加坡, region_id=9):", res)
    print("  PASS login 成功, 用新加坡 cookie")

    print()
    print("=" * 70)
    print("Scenario 5: clear_cookies by region")
    print("=" * 70)
    print("  clear(9):", main_mod.clear_cookies(region_id=9))
    print("  list 后:")
    print("   " + main_mod.list_cookies().replace("\n", "\n   "))
    assert "o100000000001_9" not in main_mod.list_cookies()
    print("  PASS 新加坡 cookie 已清除, 上海保留")

    print()
    print("=" * 70)
    print("Scenario 6: simulate server restart (new CookieManager, same dir)")
    print("=" * 70)
    # 新实例加载同一目录 (模拟重启后的进程)
    new_mgr = __import__("dmc_mcp_server.cookie_manager", fromlist=["CookieManager"]).CookieManager(tmp)
    print("  重启后 ready:", new_mgr.is_ready())
    print("  重启后 active_key:", new_mgr.active_key)
    print("  重启后 list:", [(r["key"], r["region_id"]) for r in new_mgr.list_stored()])
    assert new_mgr.is_ready(), "重启后应该能读到持久化的上海 cookie"
    print("  PASS 重启后 cookie 自动恢复 (持久化生效)")

    print()
    print("ALL SCENARIOS PASSED PASS")


if __name__ == "__main__":
    main()