from __future__ import annotations

import re

from mcp.server.fastmcp import FastMCP

from .client import DMCClient
from .cookie_manager import CookieManager

mcp = FastMCP("dmc-mcp-server")

_cookie_mgr = CookieManager()
_client: DMCClient | None = None


def _get_client() -> DMCClient:
    global _client
    if _client is None:
        if not _cookie_mgr.is_ready():
            _cookie_mgr.load_from_env()
        if not _cookie_mgr.is_ready():
            raise RuntimeError(
                "No cookie configured. Use the 'set_cookie' tool first, "
                "or set the DMC_COOKIE environment variable."
            )
        _client = DMCClient(cookie=_cookie_mgr.cookie, mc_gtk=_cookie_mgr.mc_gtk)
    return _client


def _validate_select_only(sql: str) -> str:
    stripped = sql.strip().rstrip(";").strip()

    forbidden_prefixes = [
        "insert", "update", "delete", "drop", "create", "alter",
        "truncate", "replace", "grant", "revoke", "lock", "unlock",
        "call", "handler", "load", "outfile", "dumpfile", "kill",
        "set", "do", "flush", "reset", "shutdown", "start", "stop",
        "checkpoint", "purge", "optimize", "analyze", "check",
        "repair", "backup", "restore", "clone", "install", "uninstall",
        "xa", "begin", "commit", "rollback", "savepoint",
    ]

    first_word = stripped.split()[0].lower() if stripped.split() else ""

    if first_word in forbidden_prefixes:
        raise ValueError(
            f"This MCP server only supports SELECT queries. "
            f"Detected '{first_word.upper()}' which is not allowed."
        )

    select_pattern = re.compile(
        r"^(with\s+.*?\)\s*select|select)\s",
        re.IGNORECASE | re.DOTALL,
    )
    if not select_pattern.match(stripped):
        raise ValueError(
            f"Only SELECT statements are allowed. "
            f"Query must start with SELECT or WITH...SELECT."
        )

    return stripped


# ============================================================
# MCP Tools
# ============================================================

@mcp.tool()
def set_cookie(cookie: str, mc_gtk: int = 0) -> str:
    """
    Set or update the Tencent Cloud console cookie.
    AI can obtain this from the browser via Chrome DevTools MCP:
      document.cookie
    Then pass the full cookie string here.

    The mc_gtk (csrfCode) value is required for cluster search (DescribeClusters API).
    AI can extract it from the browser's performance API:
      performance.getEntriesByType('resource')
        .find(e => e.name.includes('csrfCode='))
        ?.name.match(/csrfCode=(\\d+)/)?.[1]
    If not provided, DMC login/SQL tools will still work (they don't require mc_gtk
    to be valid), but find_instance_by_ip will fail.

    Args:
        cookie: Full cookie string from the Tencent Cloud console browser tab.
        mc_gtk: Optional csrfCode value from the browser. Required for cluster search.
    """
    _cookie_mgr.set_cookie(cookie, mc_gtk)
    global _client
    if _client is not None:
        _client.update_cookie(_cookie_mgr.cookie, _cookie_mgr.mc_gtk)
    else:
        _client = DMCClient(cookie=_cookie_mgr.cookie, mc_gtk=_cookie_mgr.mc_gtk)
    return "Cookie updated successfully. All active sessions will use the new cookie."


@mcp.tool()
def login_instance(
    instance_id: str,
    user: str,
    password: str,
    db_type: str = "cynosdbmysql",
    region_id: int = 4,
) -> str:
    """
    Login to a database instance via Tencent Cloud DMC.
    Supports both TDSQL-C (CynosDB) and TDSQL (DCDB) instances.
    The session is cached - subsequent calls reuse the same token
    without re-login, unless the token expires.

    Use find_instance_by_ip to discover the instance_id and db_type,
    then pass the db_type value from the search results here.

    Args:
        instance_id: Instance ID, e.g. "cynosdbmysql-xxx" or "tdsqlshard-xxx"
        user: Database account name, e.g. "db_user"
        password: Database account password (plain text)
        db_type: Database type - "cynosdbmysql" (TDSQL-C) or "tdsql" (TDSQL)
        region_id: Region ID, default 4 (Shanghai)

    Returns:
        Login status message.
    """
    client = _get_client()
    session = client.ensure_login(
        instance_id=instance_id,
        user=user,
        password=password,
        db_type=db_type,
        region_id=region_id,
    )
    return (
        f"Login successful. Instance: {instance_id}, "
        f"User: {user}, Token prefix: {session.token[:16]}..."
    )


@mcp.tool()
def execute_select(
    instance_id: str,
    sql: str,
    db_name: str,
    page_size: int = 50,
) -> str:
    """
    Execute a SELECT query on a logged-in database instance.
    Only SELECT statements are allowed (enforced by SQL validation).

    Args:
        instance_id: Instance ID (must be logged in via login_instance first)
        sql: SELECT SQL statement to execute
        db_name: Target database name within the instance
        page_size: Max rows to return, default 50

    Returns:
        Query results as formatted text.
    """
    safe_sql = _validate_select_only(sql)
    client = _get_client()
    data = client.execute_sql(
        instance_id=instance_id,
        sql=safe_sql,
        db_name=db_name,
        page_size=page_size,
    )

    items = data.get("items", [])
    col_info = data.get("info", [])
    col_names = [c.get("name", f"col_{i}") for i, c in enumerate(col_info)]

    if not items:
        return f"Query executed successfully. 0 rows returned. Time: {data.get('timeCost', '?')}ms"

    lines = []
    lines.append(f"{' | '.join(col_names)}")
    lines.append("-" * min(120, len(lines[0])))
    for row in items:
        vals = []
        for col_name in col_names:
            val = row.get(col_name, "")
            s = str(val)
            if len(s) > 50:
                s = s[:47] + "..."
            vals.append(s)
        lines.append(f"{' | '.join(vals)}")

    lines.append(f"\n{len(items)} rows. Time: {data.get('timeCost', '?')}ms")
    return "\n".join(lines)


@mcp.tool()
def list_databases(instance_id: str) -> str:
    """
    List all databases accessible by the current logged-in account
    on the specified instance.

    Args:
        instance_id: Instance ID (must be logged in)

    Returns:
        List of database names.
    """
    client = _get_client()
    dbs = client.list_databases(instance_id)
    return f"Databases on {instance_id}:\n" + "\n".join(f"  - {db}" for db in dbs)


@mcp.tool()
def list_tables(
    instance_id: str,
    db_name: str,
    search: str | None = None,
) -> str:
    """
    List tables in a database, optionally filtered by name pattern.

    Args:
        instance_id: Instance ID (must be logged in)
        db_name: Database name
        search: Optional table name filter (fuzzy match)

    Returns:
        Table list with row counts and sizes.
    """
    client = _get_client()
    tables = client.list_tables(instance_id, db_name, search)
    if not tables:
        return f"No tables found in '{db_name}'" + (
            f" matching '{search}'" if search else ""
        )

    lines = [f"Tables in {db_name} ({len(tables)} total):"]
    lines.append(f"{'TABLE_NAME':40s} {'ROWS':>10s} {'SIZE':>10s}  COMMENT")
    lines.append("-" * 90)
    for t in tables:
        name = str(t.get("TABLE_NAME", ""))
        rows = str(t.get("TABLE_ROWS", ""))
        size_val = t.get("DATA_LENGTH")
        size_kb = f"{int(size_val) // 1024}KB" if size_val and str(size_val).isdigit() else "N/A"
        comment = str(t.get("TABLE_COMMENT", ""))[:30]
        lines.append(f"{name:40s} {rows:>10s} {size_kb:>10s}  {comment}")

    return "\n".join(lines)


@mcp.tool()
def get_table_detail(
    instance_id: str,
    db_name: str,
    table_name: str,
) -> str:
    """
    Get detailed schema of a table: columns and DDL (CREATE TABLE statement).

    Args:
        instance_id: Instance ID (must be logged in)
        db_name: Database name
        table_name: Table name

    Returns:
        Column details and CREATE TABLE DDL.
    """
    client = _get_client()
    detail = client.get_table_detail(instance_id, db_name, table_name)

    columns = detail["columns"]
    lines = [f"Table: {db_name}.{table_name} ({len(columns)} columns)\n"]
    lines.append(
        f"{'COLUMN':30s} {'TYPE':20s} {'NULL':6s} {'KEY':6s} {'DEFAULT':15s} COMMENT"
    )
    lines.append("-" * 110)
    for col in columns:
        name = str(col.get("COLUMN_NAME", ""))
        col_type = str(col.get("COLUMN_TYPE", ""))
        nullable = str(col.get("IS_NULLABLE", ""))
        key = str(col.get("COLUMN_KEY", ""))
        default = str(col.get("COLUMN_DEFAULT", ""))[:15]
        comment = str(col.get("COLUMN_COMMENT", ""))[:40]
        lines.append(
            f"{name:30s} {col_type:20s} {nullable:6s} {key:6s} {default:15s} {comment}"
        )

    lines.append(f"\n--- DDL ---\n{detail['ddl']}")

    return "\n".join(lines)


@mcp.tool()
def list_active_sessions() -> str:
    """
    List all currently active (logged-in) database instance sessions.
    Useful to check which instances are ready for querying.

    Returns:
        List of active instance IDs and their session status.
    """
    client = _get_client()
    instances = client.active_instances
    if not instances:
        return "No active sessions. Use login_instance to connect."

    lines = [f"Active sessions ({len(instances)}):"]
    for inst_id in instances:
        lines.append(f"  - {inst_id}")
    return "\n".join(lines)


@mcp.tool()
def find_instance_by_ip(ip: str) -> str:
    """
    Find a database instance by its internal Vip (proxy IP).
    Searches both TDSQL-C (CynosDB) and TDSQL (DCDB) instances.

    Typical workflow:
      1. Read the JDBC URL from your config file (e.g. 10.0.0.1:3306)
      2. Call find_instance_by_ip("10.0.0.1") to get the InstanceId
      3. Call login_instance with the InstanceId (use the DbType from results)
      4. Call execute_select

    Args:
        ip: Internal Vip address, e.g. "10.0.0.1"

    Returns:
        Matching instance info (InstanceId, Name, Vip, DbType) or "not found".
    """
    try:
        from .cluster_search import search_all_by_ip
    except ImportError:
        return "Cluster search module not available."

    cookie = _cookie_mgr.cookie
    mc_gtk = _cookie_mgr.mc_gtk
    results = search_all_by_ip(cookie, ip, mc_gtk=mc_gtk)
    if not results:
        return f"No instance found with Vip '{ip}' in either TDSQL-C or TDSQL."

    lines = [f"Found {len(results)} instance(s) matching Vip '{ip}':"]
    for r in results:
        db_type = r.get("DbType", "unknown")
        lines.append(f"  InstanceId: {r['ClusterId']}")
        lines.append(f"  Name: {r.get('ClusterName', 'N/A')}")
        lines.append(f"  Vip: {r.get('Vip', 'N/A')}")
        lines.append(f"  DbType: {db_type}")
        if r.get("ShardCount"):
            lines.append(f"  ShardCount: {r['ShardCount']}")
        if r.get("Status"):
            lines.append(f"  Status: {r['Status']}")
        lines.append("")
    return "\n".join(lines)


def main():
    _cookie_mgr.load_from_env()
    _cookie_mgr.load_mc_gtk_from_env()
    mcp.run()


if __name__ == "__main__":
    main()
