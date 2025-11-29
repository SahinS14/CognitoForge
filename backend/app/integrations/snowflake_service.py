"""Snowflake integration helpers for CognitoForge Labs."""

from __future__ import annotations

import logging
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from threading import Lock
from typing import TYPE_CHECKING, Any, Dict, Iterable, Iterator, List, Optional, Tuple

from backend.app.core.settings import get_settings

try:  # pragma: no cover - optional dependency handling
    import snowflake.connector as _snowflake_connector  # type: ignore[import-not-found]
    from snowflake.connector.errors import Error as SnowflakeError  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - allow running without connector installed
    _snowflake_connector = None
    SnowflakeError = Exception


if TYPE_CHECKING:  # pragma: no cover - typing helper
    from snowflake.connector import SnowflakeConnection as SnowflakeConnectionType  # type: ignore[import-not-found]
else:  # pragma: no cover - runtime fallback
    SnowflakeConnectionType = Any


logger = logging.getLogger(__name__)


class _SnowflakeClient:
    """Lazy Snowflake connection manager with lightweight pooling."""

    def __init__(self, config: Dict[str, str]):
        self._config = config
        self._connection: Optional[SnowflakeConnectionType] = None
        self._lock = Lock()

    def _connect(self) -> SnowflakeConnectionType:
        if _snowflake_connector is None:  # pragma: no cover - guarded earlier
            raise RuntimeError("Snowflake connector is not installed")

        logger.info(
            "Establishing Snowflake connection",
            extra={"account": self._config.get("account"), "schema": self._config.get("schema")},
        )
        connection = _snowflake_connector.connect(**self._config)
        connection.autocommit(True)
        return connection

    def _ensure_connection(self) -> SnowflakeConnectionType:
        with self._lock:
            if self._connection is not None:
                try:
                    if not self._connection.is_closed():
                        return self._connection
                except AttributeError:
                    pass

            self._connection = self._connect()
            return self._connection

    @contextmanager
    def connection(self) -> Iterator[SnowflakeConnectionType]:
        connection = self._ensure_connection()
        try:
            yield connection
        except SnowflakeError as exc:
            logger.error("Snowflake connection error", extra={"error": str(exc)})
            raise

    def ensure_tables(self) -> None:
        table_statements = [
            """
            CREATE TABLE IF NOT EXISTS simulation_runs (
                repo_id VARCHAR,
                run_id VARCHAR,
                overall_severity VARCHAR,
                timestamp TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS affected_files (
                repo_id VARCHAR,
                run_id VARCHAR,
                file_path VARCHAR,
                severity VARCHAR
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS ai_insights (
                repo_id VARCHAR,
                run_id VARCHAR,
                insight TEXT
            )
            """,
        ]

        with self.connection() as connection:
            with connection.cursor() as cursor:
                for statement in table_statements:
                    cursor.execute(statement)


_client: Optional[_SnowflakeClient] = None
_client_lock = Lock()


def _build_config() -> Optional[Dict[str, str]]:
    settings = get_settings()
    required = {
        "account": settings.snowflake_account,
        "user": settings.snowflake_user,
        "password": settings.snowflake_password,
    }
    optional = {
        "warehouse": settings.snowflake_warehouse,
        "database": settings.snowflake_database,
        "schema": settings.snowflake_schema,
    }

    missing = [key for key, value in required.items() if not value]
    if missing:
        logger.debug("Snowflake integration skipped; missing settings", extra={"missing": missing})
        return None

    config = {key: value for key, value in {**required, **optional}.items() if value}
    return config


def init_snowflake() -> Optional[_SnowflakeClient]:
    """Initialise the Snowflake connection manager and ensure tables exist."""

    global _client

    if _client is not None:
        return _client

    if _snowflake_connector is None:
        logger.debug("Snowflake connector not installed; integrations disabled")
        return None

    config = _build_config()
    if config is None:
        return None

    with _client_lock:
        if _client is not None:
            return _client

        try:
            client = _SnowflakeClient(config)
            client.ensure_tables()
        except SnowflakeError as exc:
            logger.error(
                "Failed to initialise Snowflake integration: %s",
                exc,
                extra={"account": config.get("account")},
            )
            return None
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected Snowflake initialisation error", extra={"error": str(exc)})
            return None

        _client = client
        return _client


def _normalise_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
        except ValueError:
            pass

    return datetime.utcnow().isoformat()


def store_simulation_run(repo_id: str, run_id: str, summary: Dict[str, Any]) -> bool:
    """Persist simulation metadata into Snowflake."""

    client = init_snowflake()
    if client is None:
        return False

    overall_severity = summary.get("overall_severity") or "unknown"
    timestamp_value = summary.get("timestamp") or summary.get("event_timestamp")
    timestamp_iso = _normalise_timestamp(timestamp_value)

    try:
        with client.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO simulation_runs (repo_id, run_id, overall_severity, timestamp)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (repo_id, run_id, overall_severity, timestamp_iso),
                )
        logger.info(
            "Stored simulation run in Snowflake",
            extra={"repo_id": repo_id, "run_id": run_id, "overall_severity": overall_severity},
        )
        return True
    except SnowflakeError as exc:
        logger.error(
            "Failed to store simulation run in Snowflake: %s",
            exc,
            extra={"repo_id": repo_id, "run_id": run_id},
        )
        return False
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Unexpected error storing simulation run in Snowflake",
            extra={"repo_id": repo_id, "run_id": run_id, "error": str(exc)},
        )
        return False


def _normalise_file_entry(entry: Any) -> Optional[Tuple[str, str]]:
    if isinstance(entry, dict):
        file_path = entry.get("file_path") or entry.get("path") or entry.get("file")
        severity = entry.get("severity") or entry.get("level") or "unknown"
        if file_path:
            return str(file_path), str(severity)
        return None

    if isinstance(entry, (list, tuple)) and entry:
        file_path = entry[0]
        severity = entry[1] if len(entry) > 1 else "unknown"
        if file_path:
            return str(file_path), str(severity)
        return None

    if entry:
        return str(entry), "unknown"

    return None


def store_affected_files(repo_id: str, run_id: str, file_list: Iterable[Any]) -> bool:
    """Persist affected file records into Snowflake."""

    client = init_snowflake()
    if client is None:
        return False

    rows: List[Tuple[str, str, str, str]] = []
    for entry in file_list:
        normalised = _normalise_file_entry(entry)
        if normalised is None:
            continue
        file_path, severity = normalised
        rows.append((repo_id, run_id, file_path, severity))

    if not rows:
        return True

    try:
        with client.connection() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO affected_files (repo_id, run_id, file_path, severity)
                    VALUES (%s, %s, %s, %s)
                    """,
                    rows,
                )
        logger.info(
            "Stored affected files in Snowflake",
            extra={"repo_id": repo_id, "run_id": run_id, "count": len(rows)},
        )
        return True
    except SnowflakeError as exc:
        logger.error(
            "Failed to store affected files in Snowflake: %s",
            exc,
            extra={"repo_id": repo_id, "run_id": run_id},
        )
        return False
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Unexpected error storing affected files in Snowflake",
            extra={"repo_id": repo_id, "run_id": run_id, "error": str(exc)},
        )
        return False


def store_ai_insight(repo_id: str, run_id: str, insight: str) -> bool:
    """Persist Gemini-generated insight into Snowflake."""

    if not insight:
        return False

    client = init_snowflake()
    if client is None:
        return False

    try:
        with client.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO ai_insights (repo_id, run_id, insight)
                    VALUES (%s, %s, %s)
                    """,
                    (repo_id, run_id, insight),
                )
        logger.info(
            "Stored AI insight in Snowflake",
            extra={"repo_id": repo_id, "run_id": run_id, "length": len(insight)},
        )
        return True
    except SnowflakeError as exc:
        logger.error(
            "Failed to store AI insight in Snowflake: %s",
            exc,
            extra={"repo_id": repo_id, "run_id": run_id},
        )
        return False
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Unexpected error storing AI insight in Snowflake",
            extra={"repo_id": repo_id, "run_id": run_id, "error": str(exc)},
        )
        return False


def _fetch_report_payload(
    repo_id: str,
    run_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    client = init_snowflake()
    if client is None:
        return None

    try:
        with client.connection() as connection:
            with connection.cursor() as cursor:
                if run_id is None:
                    cursor.execute(
                        """
                        SELECT run_id, overall_severity, timestamp
                        FROM simulation_runs
                        WHERE repo_id = %s
                        ORDER BY timestamp DESC
                        LIMIT 1
                        """,
                        (repo_id,),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT run_id, overall_severity, timestamp
                        FROM simulation_runs
                        WHERE repo_id = %s AND run_id = %s
                        LIMIT 1
                        """,
                        (repo_id, run_id),
                    )
                metadata_row = cursor.fetchone()

            if not metadata_row:
                return None

            run_identifier = str(metadata_row[0])
            overall_severity = str(metadata_row[1] or "unknown")
            timestamp_value = metadata_row[2]

            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT file_path, severity
                    FROM affected_files
                    WHERE repo_id = %s AND run_id = %s
                    """,
                    (repo_id, run_identifier),
                )
                affected_rows = cursor.fetchall() or []

            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT insight
                    FROM ai_insights
                    WHERE repo_id = %s AND run_id = %s
                    LIMIT 1
                    """,
                    (repo_id, run_identifier),
                )
                insight_row = cursor.fetchone()

    except SnowflakeError as exc:
        logger.error(
            "Failed to fetch simulation report from Snowflake",
            extra={"repo_id": repo_id, "run_id": run_id, "error": str(exc)},
        )
        return None
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Unexpected error fetching simulation report from Snowflake",
            extra={"repo_id": repo_id, "run_id": run_id, "error": str(exc)},
        )
        return None

    severity_counter: Counter[str] = Counter()
    affected_files: List[str] = []
    for file_path, severity in affected_rows:
        if file_path:
            affected_files.append(str(file_path))
        normalised_severity = str(severity or "unknown").strip().lower()
        if normalised_severity:
            severity_counter[normalised_severity] += 1

    summary: Dict[str, Any] = {"overall_severity": overall_severity}
    for severity_name, count in severity_counter.items():
        summary[f"{severity_name}_steps"] = count
    summary["affected_files"] = sorted(set(affected_files))

    insight_text = str(insight_row[0]) if insight_row and insight_row[0] else None

    payload = {
        "repo_id": repo_id,
        "run_id": run_identifier,
        "summary": summary,
        "ai_insight": insight_text,
        "timestamp": _normalise_timestamp(timestamp_value),
    }

    logger.info(
        "Fetched simulation report from Snowflake",
        extra={"repo_id": repo_id, "run_id": run_identifier},
    )

    return payload


def fetch_latest_simulation_report(repo_id: str) -> Optional[Dict[str, Any]]:
    """Return the newest simulation report data from Snowflake if available."""

    return _fetch_report_payload(repo_id, None)


def fetch_simulation_report(repo_id: str, run_id: str) -> Optional[Dict[str, Any]]:
    """Return a specific simulation report from Snowflake."""

    if not run_id:
        return None
    return _fetch_report_payload(repo_id, run_id)


def fetch_severity_summary() -> Optional[Dict[str, int]]:
    """Return counts of simulation runs grouped by overall severity."""

    client = init_snowflake()
    if client is None:
        return None

    try:
        with client.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT LOWER(COALESCE(overall_severity, 'unknown')) AS severity,
                           COUNT(*) AS total
                    FROM simulation_runs
                    GROUP BY 1
                    """
                )
                rows = cursor.fetchall() or []
    except SnowflakeError as exc:
        logger.error("Failed to fetch severity summary from Snowflake: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Unexpected error fetching severity summary from Snowflake",
            extra={"error": str(exc)},
        )
        return None

    summary = {key: 0 for key in ("critical", "high", "medium", "low")}
    for severity, total in rows:
        key = str(severity or "").strip().lower()
        if key in summary:
            summary[key] = int(total)

    return summary


__all__ = [
    "init_snowflake",
    "store_simulation_run",
    "store_affected_files",
    "store_ai_insight",
    "fetch_latest_simulation_report",
    "fetch_simulation_report",
    "fetch_severity_summary",
]
