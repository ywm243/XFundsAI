import logging
import os
import oracledb
from contextlib import contextmanager
from .config import DBConfig

logger = logging.getLogger(__name__)

# Ensure Oracle NLS encoding for Chinese characters
os.environ.setdefault("NLS_LANG", "AMERICAN_AMERICA.AL32UTF8")

import platform
if platform.system() == "Windows":
    IC_DIR = r"C:\instantclient_19_30"
else:
    IC_DIR = "/home/ywm/oracle/instantclient_21_12"
_config = DBConfig()
_oracle_ready = False
_oracle_error: str | None = None
_pool = None


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
        oracledb.init_oracle_client(lib_dir=IC_DIR)
        global _pool
        _pool = oracledb.create_pool(
            user=_config.user,
            password=_config.password,
            dsn=_config.dsn,
            min=1,
            max=10,
            getmode=oracledb.POOL_GETMODE_WAIT,
        )
        _oracle_ready = True
        logger.info("Oracle client + pool initialized: %s (min=1, max=10)", IC_DIR)
    except oracledb.Error as e:
        _oracle_error = str(e)
        raise RuntimeError(
            f"Oracle Instant Client init failed: {e}\n"
            f"IC_DIR={IC_DIR}"
        ) from e


@contextmanager
def get_db():
    _ensure_oracle()
    conn = _pool.acquire()
    try:
        yield conn
    finally:
        _pool.drop(conn)
