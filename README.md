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

### 在 opencode.jsonc 中添加

```jsonc
{
  "mcp": {
    "dmc-mcp-server": {
      "type": "stdio",
      "command": "uvx",
      "args": ["dmc-mcp-server"],
      "env": {
        "DMC_COOKIE": "<从浏览器复制的腾讯云控制台Cookie>",
        "DMC_MC_GTK": "<csrfCode, 可选, 用于实例搜索>"
      }
    }
  }
}
```

### Cookie 获取方式

AI 可通过 Chrome DevTools MCP 自动获取：

```javascript
// Cookie
document.cookie

// mc_gtk (csrfCode) - 从 performance API 提取
performance.getEntriesByType('resource')
  .find(e => e.name.includes('csrfCode='))
  ?.name.match(/csrfCode=(\d+)/)?.[1]
```

也可运行时通过 `set_cookie` 工具动态更新。

## 工具列表

| 工具 | 说明 |
|------|------|
| `set_cookie` | 设置/更新腾讯云控制台 Cookie + mc_gtk |
| `find_instance_by_ip` | 通过内网 IP 搜索数据库实例（同时搜 TDSQL-C 和 TDSQL） |
| `login_instance` | 登录数据库实例（会话缓存，不重复登录） |
| `execute_select` | 执行 SELECT 查询（仅允许 SELECT） |
| `list_databases` | 列出实例上的所有数据库 |
| `list_tables` | 列出指定库的表（支持模糊搜索） |
| `get_table_detail` | 查看表结构（列信息 + DDL） |
| `list_active_sessions` | 查看已登录的实例列表 |

## 支持的数据库类型

| 类型 | dbType | 实例ID前缀 | 搜索 API |
|------|--------|-----------|---------|
| TDSQL-C (CynosDB) | `cynosdbmysql` | `cynosdbmysql-` | `cynosdb.cloud.tencent.com` DescribeClusters |
| TDSQL (DCDB) | `tdsql` | `tdsqlshard-` | `tdsql.cloud.tencent.com` DescribeDCDBInstances |

`find_instance_by_ip` 会同时搜索两种类型，返回结果中包含 `DbType` 字段供 `login_instance` 使用。

## 特性

- **双类型支持**：同时支持 TDSQL-C (CynosDB) 和 TDSQL (DCDB) 实例
- **仅 SELECT**：SQL 执行层强制限制只允许 SELECT 语句
- **会话复用**：登录过的实例自动缓存 token，不重复登录
- **自动重连**：token 过期时自动重新登录（使用缓存的凭据）
- **Cookie 动态更新**：运行时通过工具更新，无需重启 Server
- **代理兼容**：自动清除系统代理环境变量，避免 socks5 代理导致连接卡死

## 约束

- Cookie 有效期约 2 小时（腾讯云控制台标准），过期需重新获取
- SQL 仅支持 SELECT（WITH...SELECT 也允许）
- DB 权限取决于 DB 账号本身的 GRANT 权限
- TDSQL 需要数据库账号已对 DMC 服务器 IP 段授权（否则登录报 ACCESS_DENIED）

## License

MIT
