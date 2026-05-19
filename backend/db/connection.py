import logging
import os
from contextlib import contextmanager
from .config import DBConfig

logger = logging.getLogger(__name__)

# Ensure Oracle NLS encoding for Chinese characters
os.environ.setdefault("NLS_LANG", "AMERICAN_AMERICA.AL32UTF8")

import platform
if platform.system() == "Windows":
    IC_DIR = r"D:\soft\instantclient\instantclient_19_19"
else:
    IC_DIR = "/home/ywm/oracle/instantclient_21_12"
_config = DBConfig()
_oracle_ready = False
_oracle_error: str | None = None
_pool = None


def _session_callback(conn, tag=None):
    """Initialize NLS settings for each pooled connection."""
    with conn.cursor() as cur:
        cur.execute("ALTER SESSION SET NLS_DATE_FORMAT='YYYY-MM-DD'")
        cur.execute("ALTER SESSION SET NLS_NUMERIC_CHARACTERS='.,'")


def _ensure_oracle() -> None:
    """Lazy-init Oracle client on first use (not on import).

    Server starts without Oracle; only query execution requires it.
    """
    global _oracle_ready, _oracle_error
    if _oracle_ready:
        return
    if _oracle_error:
        raise RuntimeError(_oracle_error)

    try:
        # Thick mode: required for older Oracle DB versions (thin mode unsupported)
        # Set DLL search path BEFORE importing oracledb to ensure oci.dll is found
        if platform.system() == "Windows":
            import ctypes
            ctypes.windll.kernel32.SetDllDirectoryW(IC_DIR)
        else:
            os.environ["LD_LIBRARY_PATH"] = IC_DIR + os.pathsep + os.environ.get("LD_LIBRARY_PATH", "")
        import oracledb
        oracledb.init_oracle_client(lib_dir=IC_DIR)
        global _pool
        _pool = oracledb.create_pool(
            user=_config.user,
            password=_config.password,
            dsn=_config.dsn,
            min=1,
            max=10,
            getmode=oracledb.POOL_GETMODE_WAIT,
            session_callback=_session_callback,
        )
        _oracle_ready = True
        logger.info("Oracle thick pool initialized: %s (min=1, max=10, lib=%s)", _config.dsn, IC_DIR)
    except oracledb.Error as e:
        _oracle_error = str(e)
        raise RuntimeError(
            f"Oracle pool init failed: {e}\n"
            f"DSN={_config.dsn}, IC_DIR={IC_DIR}"
        ) from e


@contextmanager
def get_db():
    _ensure_oracle()
    conn = _pool.acquire()
    try:
        yield conn
    finally:
        _pool.release(conn)
