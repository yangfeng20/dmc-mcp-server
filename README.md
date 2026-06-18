# dmc-mcp-server

通过腾讯云 DMC (Data Management Console) 在 TDSQL-C / CDB 数据库实例上执行 SQL 查询的 MCP Server。

## 原理

```
浏览器 (腾讯云控制台登录态)
    │  Cookie (skey/uin)
    ▼
DMC MCP Server
    │  ① RSA 加密 DB 密码 (PKCS#1 v1.5)
    │  ② POST /api/mysql/dbLogin → token
    │  ③ POST /api/mysql/schemaAdmin/commonSql → 查询结果
    ▼
TDSQL-C MySQL (内网 10.0.x)
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
        "DMC_COOKIE": "<从浏览器复制的腾讯云控制台Cookie>"
      }
    }
  }
}
```

### Cookie 获取方式

AI 可通过 Chrome DevTools MCP 自动获取：

```javascript
document.cookie
```

或手动从浏览器 DevTools → Application → Cookies 复制。

也可运行时通过 `set_cookie` 工具动态更新。

## 工具列表

| 工具 | 说明 |
|------|------|
| `set_cookie` | 设置/更新腾讯云控制台 Cookie |
| `login_instance` | 登录数据库实例（会话缓存，不重复登录） |
| `execute_select` | 执行 SELECT 查询（仅允许 SELECT） |
| `list_databases` | 列出实例上的所有数据库 |
| `list_tables` | 列出指定库的表（支持模糊搜索） |
| `get_table_detail` | 查看表结构（列信息 + DDL） |
| `list_active_sessions` | 查看已登录的实例列表 |

## 特性

- **仅 SELECT**：SQL 执行层强制限制只允许 SELECT 语句
- **会话复用**：登录过的实例自动缓存 token，不重复登录
- **自动重连**：token 过期时自动重新登录（使用缓存的凭据）
- **Cookie 动态更新**：运行时通过工具更新，无需重启 Server

## 约束

- Cookie 有效期约 2 小时（腾讯云控制台标准），过期需重新获取
- SQL 仅支持 SELECT（WITH...SELECT 也允许）
- DB 权限取决于 DB 账号本身的 GRANT 权限
