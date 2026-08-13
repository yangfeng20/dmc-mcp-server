# dmc-mcp-server

通过腾讯云 DMC (Data Management Console) 在 TDSQL-C / TDSQL 数据库实例上执行 SQL 查询的 MCP Server。

## 原理

```
浏览器 (腾讯云控制台登录态)
    │  Cookie (skey/uin) + mc_gtk (csrfCode)
    ▼
DMC MCP Server
    │  ① 按实例类型搜索 API:
    │     TDSQL-C → cynosdb.cloud.tencent.com DescribeClusters (本地过滤 Vip)
    │     TDSQL   → tdsql.cloud.tencent.com DescribeDCDBInstances (服务端 SearchKey)
    │  ② RSA 加密 DB 密码 (PKCS#1 v1.5)
    │  ③ POST dms.cloud.tencent.com/api/mysql/dbLogin → token
    │  ④ POST dms.cloud.tencent.com/api/mysql/schemaAdmin/commonSql → 查询结果
    ▼
TDSQL-C / TDSQL MySQL (内网 IP)
```

利用腾讯云 DMC 控制台的 Web API，通过浏览器 Cookie 复用登录态，实现从本地对生产内网数据库的 SQL 查询。

## 安装

### 方式一：uvx 一键运行（推荐）

```bash
uvx dmc-mcp-server
```

### 方式二：从源码安装

```bash
cd dmc-mcp-server
uv sync
uv run dmc-mcp-server
```

## 配置

### 在 MCP 客户端中添加

在你的 MCP 客户端配置中添加 (如 `opencode.jsonc`, `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "dmc-mcp-server": {
      "command": "uvx",
      "args": ["dmc-mcp-server"]
    }
  }
}
```

> Cookie 不写在配置中, 启动后通过 `set_cookie` 工具动态设置.

### Cookie 获取方式

启动 MCP 后, 通过 Chrome DevTools MCP 在腾讯云控制台页面自动获取:

```javascript
// Cookie
document.cookie

// mc_gtk (csrfCode) - 从 performance API 提取
performance.getEntriesByType('resource')
  .find(e => e.name.includes('csrfCode='))
  ?.name.match(/csrfCode=(\d+)/)?.[1]
```

然后调用 `set_cookie(cookie, mc_gtk)` 工具设置.

> 也可手动从浏览器 DevTools 复制 `document.cookie` 的值, 但 mc_gtk 必须从 performance API 提取.

## 工具列表

| 工具 | 说明 |
|------|------|
| `set_cookie` | 设置/更新腾讯云控制台 Cookie + mc_gtk |
| `find_instance_by_ip` | 通过内网 IP 搜索数据库实例（同时搜 TDSQL-C 和 TDSQL） |
| `login_instance` | 登录数据库实例（会话缓存，不重复登录） |
| `execute_select` | 执行 SELECT 查询（仅允许 SELECT） |
| `execute_dml` | 执行 DML/DDL 写语句（INSERT/UPDATE/DELETE/REPLACE/ALTER/CREATE/DROP/TRUNCATE/RENAME，需二次确认） |
| `list_databases` | 列出实例上的所有数据库 |
| `list_tables` | 列出指定库的表（支持模糊搜索） |
| `get_table_detail` | 查看表结构（列信息 + DDL） |
| `list_active_sessions` | 查看已登录的实例列表 |

## DML 执行

`execute_dml` 工具用于在生产环境执行 DML/DDL 写语句，采用两步确认流程和硬编码安全校验。

> ⚠️ **高风险工具**：此工具会修改数据且不可回滚。AI agent 必须先以 `confirm=False` 预览，等用户明确说「确认」「执行」后，才能以 `confirm=True` 调用。

### 使用流程

```python
# 第一步: 预览 (confirm=False, 默认)
# 校验 SQL 但不执行, 返回预览信息
result = execute_dml(
    instance_id="cynosdbmysql-xxx",
    sql="UPDATE voip_caller_account SET shelf_status = 2 WHERE caller_account_id = 8277220",
    db_name="byrobot-prod",
    confirm=False,
)
# 返回: "Validation passed. Call again with confirm=True to execute: ..."

# 第二步: 确认执行 (confirm=True)
# 必须等用户明确确认后才调用
result = execute_dml(
    instance_id="cynosdbmysql-xxx",
    sql="UPDATE voip_caller_account SET shelf_status = 2 WHERE caller_account_id = 8277220",
    db_name="byrobot-prod",
    confirm=True,
)
# 返回: "DML executed successfully. Affected rows: 1 ..."
```

### 安全机制

以下校验硬编码在 `_validate_dml` 函数中，不可配置：

1. **语句类型限制**：仅允许 INSERT/UPDATE/DELETE/REPLACE/ALTER/CREATE/DROP/TRUNCATE/RENAME，拒绝 SELECT/其他
2. **多语句拦截**：禁止分号分隔的多语句（防 SQL 注入式攻击）
3. **WHERE 强制**：UPDATE/DELETE 必须包含 WHERE 子句（防全表误更新/误删）
4. **二次确认**：必须显式传 `confirm=True` 才真正执行，默认 `confirm=False` 仅返回预览

### AI Agent 使用约束

工具 docstring 中明确要求 AI agent 遵守以下规则：

- **禁止**：未获用户明确确认就调用 `confirm=True`
- **必须**：先以 `confirm=False` 预览，向用户展示 SQL 和影响范围
- **必须**：等待用户明确说「确认」「执行」「confirm」等词汇后，才执行
- **建议**：未确认时返回预览结果并主动询问用户是否确认执行

无需任何环境变量配置，开箱即用。

## 支持的数据库类型

| 类型 | dbType | 实例ID前缀 | 搜索 API |
|------|--------|-----------|---------|
| TDSQL-C (CynosDB) | `cynosdbmysql` | `cynosdbmysql-` | `cynosdb.cloud.tencent.com` DescribeClusters |
| TDSQL (DCDB) | `tdsql` | `tdsqlshard-` | `tdsql.cloud.tencent.com` DescribeDCDBInstances |

`find_instance_by_ip` 会同时搜索两种类型，返回结果中包含 `DbType` 字段供 `login_instance` 使用。

## 地域 (Region)

`login_instance` 的 `region_id` 参数和 `find_instance_by_ip` 的 `region` 参数用于指定集群所在地域。

**默认值**: `region_id=4` / `region="ap-shanghai"` (上海)

如果你的集群在其他地域，需要传入对应的值:

| 地域 | region_id | region (API 参数) |
|------|-----------|------------------|
| 北京 | 1 | `ap-beijing` |
| 上海 | 4 | `ap-shanghai` |
| 广州 | 7 | `ap-guangzhou` |
| 深圳 | 11 | `ap-shenzhen` |
| 成都 | 16 | `ap-chengdu` |
| 重庆 | 23 | `ap-chongqing` |
| 南京 | 45 | `ap-nanjing` |
| 香港 | 21 | `ap-hongkong` |
| 新加坡 | 15 | `ap-singapore` |
| 硅谷 | 13 | `na-siliconvalley` |
| 法兰克福 | 17 | `eu-frankfurt` |

> 完整列表见 [腾讯云地域文档](https://cloud.tencent.com/document/product/213/6091)

## 特性

- **双类型支持**：同时支持 TDSQL-C (CynosDB) 和 TDSQL (DCDB) 实例
- **SELECT 安全**：`execute_select` 强制限制只允许 SELECT 语句
- **DML/DDL 二次确认**：`execute_dml` 支持受控执行 DML/DDL 写语句，带 WHERE 强制和多语句拦截
- **会话复用**：登录过的实例自动缓存 token，不重复登录
- **自动重连**：token 过期时自动重新登录（使用缓存的凭据）
- **Cookie 动态更新**：运行时通过工具更新，无需重启 Server
- **代理兼容**：自动清除系统代理环境变量，避免 socks5 代理导致连接卡死

## 约束

- Cookie 有效期约 2 小时（腾讯云控制台标准），过期需重新获取
- `execute_select` 仅支持 SELECT（WITH...SELECT 也允许）
- `execute_dml` 支持 DML/DDL 写语句，带硬编码安全校验
- DB 权限取决于 DB 账号本身的 GRANT 权限
- TDSQL 需要数据库账号已对 DMC 服务器 IP 段授权（否则登录报 ACCESS_DENIED）

## License

MIT
