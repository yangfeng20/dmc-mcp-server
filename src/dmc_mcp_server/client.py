from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

import httpx

from .crypto import encrypt_password

DMC_BASE = "https://dms.cloud.tencent.com"
SESSION_TOKEN_TTL = 7200


@dataclass
class InstanceCredentials:
    instance_id: str
    user: str
    password: str
    db_type: str = "cynosdbmysql"
    region_id: int = 4


@dataclass
class InstanceSession:
    credentials: InstanceCredentials
    token: str
    logged_in_at: float = field(default_factory=time.time)

    @property
    def instance_id(self) -> str:
        return self.credentials.instance_id

    @property
    def db_type(self) -> str:
        return self.credentials.db_type

    @property
    def region_id(self) -> int:
        return self.credentials.region_id

    def is_expired(self) -> bool:
        return (time.time() - self.logged_in_at) > SESSION_TOKEN_TTL


class SessionExpiredError(Exception):
    pass


class DMCClient:
    def __init__(self, cookie: str, mc_gtk: int = 0):
        self._cookie = cookie
        self._mc_gtk = mc_gtk
        self._sessions: dict[str, InstanceSession] = {}
        self._creds_registry: dict[str, InstanceCredentials] = {}
        self._http = httpx.Client(trust_env=False, timeout=60)

    def _headers(self, request_id: str | None = None) -> dict:
        rid = request_id or str(uuid.uuid4())
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Cookie": self._cookie,
            "Origin": DMC_BASE,
            "Referer": f"{DMC_BASE}/v3/mysql/index.html",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/149.0.0.0 Safari/537.36"
            ),
            "X-Sequence-ID": rid,
        }

    def update_cookie(self, cookie: str, mc_gtk: int = 0):
        self._cookie = cookie
        if mc_gtk:
            self._mc_gtk = mc_gtk

    def ensure_login(
        self,
        instance_id: str,
        user: str,
        password: str,
        db_type: str = "cynosdbmysql",
        region_id: int = 4,
    ) -> InstanceSession:
        creds = InstanceCredentials(
            instance_id=instance_id,
            user=user,
            password=password,
            db_type=db_type,
            region_id=region_id,
        )
        self._creds_registry[instance_id] = creds

        session = self._sessions.get(instance_id)
        if session and not session.is_expired():
            if self._ping(session):
                return session
            del self._sessions[instance_id]

        return self._do_login(creds)

    def _do_login(self, creds: InstanceCredentials) -> InstanceSession:
        request_id = str(uuid.uuid4())
        url = (
            f"{DMC_BASE}/api/mysql/dbLogin"
            f"?_requestId={request_id}&_t={int(time.time() * 1000)}&_drc=1"
        )
        payload = {
            "dbType": creds.db_type,
            "regionId": creds.region_id,
            "uInstanceId": creds.instance_id,
            "password": encrypt_password(creds.password),
            "user": creds.user,
            "mc_gtk": self._mc_gtk,
            "token": "",
            "db_type": "",
            "globalCharset": None,
        }

        resp = self._http.post(url, json=payload, headers=self._headers(request_id))
        data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(
                f"DMC login failed for '{creds.instance_id}': "
                f"{data.get('msg', data)}"
            )

        token = data["data"]["token"]
        session = InstanceSession(credentials=creds, token=token)
        self._sessions[creds.instance_id] = session
        return session

    def _ping(self, session: InstanceSession) -> bool:
        request_id = str(uuid.uuid4())
        url = (
            f"{DMC_BASE}/api/mysql/schemaAdmin/commonSql"
            f"?_requestId={request_id}&_t={int(time.time() * 1000)}"
            f"&_ins={session.instance_id}"
        )
        payload = {
            "sql": "SELECT 1",
            "dbName": "information_schema",
            "pageSize": 1,
            "isGettingCount": 0,
            "mc_gtk": self._mc_gtk,
            "token": session.token,
            "db_type": session.db_type,
            "dbType": session.db_type,
            "globalCharset": "utf8mb4",
        }

        try:
            resp = self._http.post(url, json=payload, headers=self._headers(request_id), timeout=10)
            data = resp.json()
            return data.get("code") == 0
        except Exception:
            return False

    def _get_valid_session(self, instance_id: str) -> InstanceSession:
        session = self._sessions.get(instance_id)
        if session is None:
            creds = self._creds_registry.get(instance_id)
            if creds is None:
                raise RuntimeError(
                    f"Instance '{instance_id}' not logged in. "
                    f"Call ensure_login first."
                )
            return self._do_login(creds)

        if session.is_expired():
            del self._sessions[instance_id]
            creds = self._creds_registry[instance_id]
            return self._do_login(creds)

        return session

    def _execute_with_retry(
        self,
        instance_id: str,
        sql: str,
        db_name: str,
        page_size: int = 50,
        is_getting_count: int = 1,
    ) -> dict:
        session = self._get_valid_session(instance_id)

        try:
            return self._call_common_sql(
                session, sql, db_name, page_size, is_getting_count
            )
        except SessionExpiredError:
            del self._sessions[instance_id]
            creds = self._creds_registry[instance_id]
            session = self._do_login(creds)
            return self._call_common_sql(
                session, sql, db_name, page_size, is_getting_count
            )

    def _call_common_sql(
        self,
        session: InstanceSession,
        sql: str,
        db_name: str,
        page_size: int,
        is_getting_count: int,
    ) -> dict:
        request_id = str(uuid.uuid4())
        url = (
            f"{DMC_BASE}/api/mysql/schemaAdmin/commonSql"
            f"?_requestId={request_id}&_t={int(time.time() * 1000)}"
            f"&_ins={session.instance_id}"
        )
        payload = {
            "sql": sql,
            "dbName": db_name,
            "pageSize": page_size,
            "isGettingCount": is_getting_count,
            "mc_gtk": self._mc_gtk,
            "token": session.token,
            "db_type": session.db_type,
            "dbType": session.db_type,
            "globalCharset": "utf8mb4",
        }

        resp = self._http.post(url, json=payload, headers=self._headers(request_id))
        data = resp.json()

        if data.get("code") != 0:
            msg = data.get("msg", "")
            if self._is_session_error(msg, data.get("code")):
                raise SessionExpiredError(
                    f"Session expired for '{session.instance_id}'"
                )
            raise RuntimeError(f"SQL execution failed: {msg}")

        return data["data"]

    @staticmethod
    def _is_session_error(msg: str, code: int) -> bool:
        expired_keywords = [
            "session",
            "token",
            "expired",
            "invalid",
            "unauthorized",
            "login",
            "timeout",
        ]
        msg_lower = msg.lower()
        return any(kw in msg_lower for kw in expired_keywords)

    def execute_sql(
        self,
        instance_id: str,
        sql: str,
        db_name: str,
        page_size: int = 50,
    ) -> dict:
        return self._execute_with_retry(
            instance_id, sql, db_name, page_size, is_getting_count=1
        )

    def list_databases(self, instance_id: str) -> list[str]:
        result = self.execute_sql(
            instance_id, "SHOW DATABASES", db_name="information_schema"
        )
        items = result.get("items", [])
        return [list(row.values())[0] for row in items]

    def list_tables(
        self, instance_id: str, db_name: str, search: str | None = None
    ) -> list[dict]:
        safe_db = db_name.replace("'", "''")
        where = f"WHERE TABLE_SCHEMA = '{safe_db}'"
        if search:
            safe_search = search.replace("'", "''")
            where += f" AND TABLE_NAME LIKE '%{safe_search}%'"

        sql = (
            f"SELECT TABLE_NAME, TABLE_ROWS, DATA_LENGTH, TABLE_COMMENT "
            f"FROM information_schema.TABLES {where} ORDER BY TABLE_NAME"
        )
        result = self.execute_sql(
            instance_id, sql, db_name=db_name, page_size=200
        )
        return result.get("items", [])

    def get_table_detail(
        self, instance_id: str, db_name: str, table_name: str
    ) -> dict:
        safe_db = db_name.replace("'", "''")
        safe_table = table_name.replace("'", "''")

        cols_sql = (
            f"SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_KEY, "
            f"COLUMN_DEFAULT, EXTRA, COLUMN_COMMENT "
            f"FROM information_schema.COLUMNS "
            f"WHERE TABLE_SCHEMA = '{safe_db}' AND TABLE_NAME = '{safe_table}' "
            f"ORDER BY ORDINAL_POSITION"
        )
        result = self.execute_sql(
            instance_id, cols_sql, db_name=db_name, page_size=200
        )
        columns = result.get("items", [])

        ddl_result = self.execute_sql(
            instance_id,
            f"SHOW CREATE TABLE `{safe_db}`.`{safe_table}`",
            db_name=db_name,
            page_size=1,
        )
        ddl_items = ddl_result.get("items", [])
        ddl = ddl_items[0].get("Create Table", "") if ddl_items else ""

        return {"columns": columns, "ddl": ddl}

    @property
    def active_instances(self) -> list[str]:
        return list(self._sessions.keys())
