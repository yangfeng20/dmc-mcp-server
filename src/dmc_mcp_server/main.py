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
        _client = DMCClient(
            cookie=_cookie_mgr.cookie,
            mc_gtk=_cookie_mgr.mc_gtk,
        )
        _client.set_account_key(_cookie_mgr.active_key)
    return _client


def _set_client_cookie(cookie: str, mc_gtk: int = 0) -> None:
    """Create or update the shared DMCClient with a specific cookie."""
    global _client
    if _client is not None:
        _client.update_cookie(cookie, mc_gtk)
        _client.set_account_key(_cookie_mgr.active_key)
    else:
        _client = DMCClient(cookie=cookie, mc_gtk=mc_gtk)
        _client.set_account_key(_cookie_mgr.active_key)


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


_WRITE_OPERATIONS = frozenset({
    "insert", "update", "delete", "replace",
    "alter", "create", "drop", "truncate", "rename",
})


def _validate_write_sql(sql: str) -> str:
    """Validate a single DML or DDL write statement.

    Security checks (hardcoded, no config):
      1. Statement type must be DML or DDL
      2. No multi-statement (no semicolon inside)
      3. UPDATE/DELETE must have WHERE clause

    Args:
        sql: Raw SQL string from user.

    Returns:
        Cleaned SQL string (stripped, trailing semicolon removed).

    Raises:
        ValueError: If any check fails.
    """
    stripped = sql.strip().rstrip(";").strip()
    if not stripped:
        raise ValueError("SQL cannot be empty")

    tokens = stripped.split()
    first_word = tokens[0].lower() if tokens else ""

    if first_word not in _WRITE_OPERATIONS:
        raise ValueError(
            f"Only write operations (INSERT/UPDATE/DELETE/REPLACE/ALTER/CREATE/DROP/TRUNCATE/RENAME) are allowed. "
            f"Detected '{first_word.upper()}'."
        )

    if ";" in stripped:
        raise ValueError(
            "Multi-statement SQL is forbidden (detected semicolon)."
        )

    if first_word in ("update", "delete"):
        if not re.search(r"\bWHERE\b", stripped, re.IGNORECASE):
            raise ValueError(
                f"{first_word.upper()} statement must include a WHERE clause."
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

    The cookie is PERSISTED to disk (~/.dmc-mcp-server/cookie/), keyed by
    account uin + region_id parsed from the cookie itself. This means:
      - Once set, future sessions / agents reuse it without re-setting.
      - Shanghai (region_id=4) and Singapore (region_id=9) cookies are stored
        separately and never mixed.
    Use list_cookies to see what is stored, and clear_cookies to remove.

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
    msg = _cookie_mgr.set_cookie(cookie, mc_gtk)
    _set_client_cookie(_cookie_mgr.cookie, _cookie_mgr.mc_gtk)
    return msg


@mcp.tool()
def list_cookies() -> str:
    """
    List all persisted Tencent Cloud console cookies (account + region).
    Useful to see which environments are ready (e.g. Shanghai vs Singapore)
    and whether any stored cookie has exceeded the ~2h lifetime (likely expired).

    Returns:
        A table of stored cookies: key, uin, region_id, age, expired flag.
    """
    rows = _cookie_mgr.list_stored()
    if not rows:
        return (
            "No persisted cookies. Use set_cookie with a cookie from the "
            "Tencent Cloud console to persist one."
        )

    lines = [f"Stored cookies ({len(rows)}):"]
    lines.append(f"{'KEY':28s} {'UIN':18s} {'REGION':>8s} {'AGE':>10s}  STATUS")
    lines.append("-" * 90)
    for r in rows:
        age_m = r["age_seconds"] // 60
        status = "EXPIRED (re-set cookie)" if r["expired"] else "ok"
        lines.append(
            f"{r['key']:28s} {str(r['uin']):18s} {r['region_id']:>8d} "
            f"{age_m:>8d}m  {status}"
        )
    return "\n".join(lines)


@mcp.tool()
def clear_cookies(region_id: int | None = None) -> str:
    """
    Delete a persisted cookie. If region_id is given, clears the cookie for that
    region (e.g. 4=Shanghai, 9=Singapore); otherwise clears the active cookie.

    Args:
        region_id: Optional region to clear (4=Shanghai, 9=Singapore).

    Returns:
        Confirmation of what was removed.
    """
    removed = _cookie_mgr.clear_region(region_id=region_id)
    if not removed:
        return "Nothing to clear."
    _set_client_cookie(_cookie_mgr.cookie, _cookie_mgr.mc_gtk)
    return f"Cleared cookie(s): {', '.join(removed)}"


@mcp.tool()
def login_instance(
    instance_id: str,
    user: str = "",
    password: str = "",
    db_type: str = "cynosdbmysql",
    region_id: int = 4,
) -> str:
    """
    Login to a database instance via Tencent Cloud DMC.
    Supports both TDSQL-C (CynosDB) and TDSQL (DCDB) instances.
    The session is cached - subsequent calls reuse the same token
    without re-login, unless the token expires.

    Persisted credentials: if the same instance was logged in before under the
    current account+region, its user/password are reused automatically, so you
    can omit user/password on repeat logins.

    Use find_instance_by_ip to discover the instance_id and db_type,
    then pass the db_type value from the search results here.

    Args:
        instance_id: Instance ID, e.g. "cynosdbmysql-xxx" or "tdsqlshard-xxx"
        user: Database account name, e.g. "db_user" (optional if previously saved)
        password: Database account password (optional if previously saved)
        db_type: Database type - "cynosdbmysql" (TDSQL-C) or "tdsql" (TDSQL)
        region_id: Region ID, 4=Shanghai (default), 9=Singapore.

    Returns:
        Login status message.
    """
    client = _get_client()

    # Ensure the client cookie + account key match the requested region.
    # (login may be called directly without a preceding find_instance_by_ip.)
    region_cookie = _cookie_mgr.get_for_region(region_id=region_id)
    if region_cookie:
        _set_client_cookie(
            region_cookie,
            _cookie_mgr.store.get_mc_gtk(region_id=region_id),
        )

    session = client.ensure_login(
        instance_id=instance_id,
        user=user,
        password=password,
        db_type=db_type,
        region_id=region_id,
    )
    return (
        f"Login successful. Instance: {instance_id}, "
        f"User: {session.credentials.user}, Token prefix: {session.token[:16]}..."
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

    max_col_name_len = max(len(c) for c in col_names)
    lines = []
    lines.append(" | ".join(col_names))
    lines.append("-" * min(200, max_col_name_len * len(col_names)))
    for row in items:
        vals = []
        for col_name in col_names:
            val = row.get(col_name, "")
            vals.append(str(val))
        lines.append(" | ".join(vals))

    lines.append(f"\n{len(items)} rows. Time: {data.get('timeCost', '?')}ms")
    return "\n".join(lines)


@mcp.tool()
def execute_dml(
    instance_id: str,
    sql: str,
    db_name: str,
    confirm: bool = False,
) -> str:
    """
    ⚠️ HIGH-RISK TOOL: Execute a DML or DDL write statement
    on a database instance. This tool modifies data and is irreversible.

    AI AGENT RULES (MANDATORY):
      - NEVER call this tool with confirm=True without explicit user approval.
      - ALWAYS call with confirm=False first to show the user the preview.
      - Wait for the user to explicitly say "confirm" / "确认" / "执行" before
        calling again with confirm=True.
      - If the user has not explicitly confirmed, return the preview result and
        ask the user to confirm.

    Two-step confirmation flow:
      1. confirm=False (default): validate the SQL and return a preview.
         The SQL is NOT executed. Safe to call.
      2. confirm=True: EXECUTES the SQL. Only call this after the user has
         explicitly confirmed.

    Security checks (hardcoded, no config):
      - Statement must be DML or DDL
      - No multi-statement (semicolon inside SQL is forbidden)
      - UPDATE/DELETE must include a WHERE clause

    Args:
        instance_id: Instance ID (must be logged in via login_instance first)
        sql: DML statement to execute
        db_name: Target database name within the instance
        confirm: Set to True to actually execute. Default False (preview only).
                 MUST be True only after explicit user confirmation.

    Returns:
        confirm=False: validation result + preview of the SQL.
        confirm=True: execution result with affected rows count.
    """
    cleaned_sql = _validate_write_sql(sql)

    if not confirm:
        return (
            f"Validation passed. Call again with confirm=True to execute:\n"
            f"{cleaned_sql}"
        )

    client = _get_client()
    data = client.execute_sql(
        instance_id=instance_id,
        sql=cleaned_sql,
        db_name=db_name,
        page_size=1,
    )

    items = data.get("items", {})
    if isinstance(items, dict):
        affected_rows = items.get("affectedRows", "N/A")
        info = items.get("info", "")
    else:
        affected_rows = "N/A"
        info = ""

    lines = [
        "SQL executed successfully.",
        f"Affected rows: {affected_rows}",
    ]
    if info:
        lines.append(f"Info: {info}")
    lines.append(f"Time: {data.get('timeCost', '?')}ms")
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
    include_ddl: bool = False,
) -> str:
    """
    Get detailed schema of a table: columns and optionally DDL (CREATE TABLE statement).

    Args:
        instance_id: Instance ID (must be logged in)
        db_name: Database name
        table_name: Table name
        include_ddl: If True, also return the CREATE TABLE DDL. Default False
                     (columns only) to save context. Set True when you need exact
                     column definitions, index definitions, or charset info.

    Returns:
        Column details (and CREATE TABLE DDL if include_ddl=True).
    """
    client = _get_client()
    detail = client.get_table_detail(instance_id, db_name, table_name, include_ddl=include_ddl)

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

    if include_ddl:
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
def find_instance_by_ip(ip: str, region: str = "ap-shanghai") -> str:
    """
    Find a database instance by its internal Vip (proxy IP).
    Searches both TDSQL-C (CynosDB) and TDSQL (DCDB) instances.

    Typical workflow:
      1. Read the JDBC URL from your config file (e.g. 10.0.0.1:3306)
      2. Call find_instance_by_ip("10.0.0.1", region="ap-guangzhou") to get the InstanceId
      3. Call login_instance with the InstanceId (use the DbType from results, and match region_id)
      4. Call execute_select

    Args:
        ip: Internal Vip address, e.g. "10.0.0.1"
        region: Tencent Cloud region string, e.g. "ap-shanghai" (default), "ap-beijing", "ap-guangzhou".
                Must match the region where your cluster is deployed.

    Returns:
        Matching instance info (InstanceId, Name, Vip, DbType) or "not found".
    """
    try:
        from .cluster_search import search_all_by_ip
    except ImportError:
        return "Cluster search module not available."

    rid = CookieManager._region_alias_to_id(region)

    # Auto-load the persisted cookie for the target region (environment switch).
    # Only when the requested region differs from the active one, or none active.
    if rid is not None:
        region_cookie = _cookie_mgr.get_for_region(region_id=rid)
        if region_cookie is None:
            # No stored cookie for this region: do not silently use another one.
            return (
                f"No stored cookie for region '{region}'. "
                f"Use set_cookie with a fresh cookie from the '{region}' console first. "
                f"Check stored cookies with list_cookies."
            )
        _set_client_cookie(region_cookie, _cookie_mgr.mc_gtk)
        cookie = region_cookie
        # mc_gtk must follow the region, not the global active value (which
        # reflects the LAST set_cookie call and may belong to another region).
        mc_gtk = _cookie_mgr.store.get_mc_gtk(region_id=rid)
    else:
        cookie = _cookie_mgr.cookie
        mc_gtk = _cookie_mgr.mc_gtk

    # Warn when the stored cookie for this region may be expired.
    if rid is not None:
        key = _cookie_mgr.store._find_key_by_region(rid)
        if key and _cookie_mgr.store.is_expired(key):
            return (
                f"⚠️ The stored cookie for region '{region}' is older than 2h and may be expired. "
                f"Re-run set_cookie with a fresh cookie from the console before trusting results.\n\n"
                + _run_search(cookie, mc_gtk, ip, region)
            )

    return _run_search(cookie, mc_gtk, ip, region)


def _run_search(cookie: str, mc_gtk: int, ip: str, region: str) -> str:
    """Shared cluster-search path used by find_instance_by_ip."""
    from .cluster_search import search_all_by_ip

    results = search_all_by_ip(cookie, ip, mc_gtk=mc_gtk, region=region)
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
