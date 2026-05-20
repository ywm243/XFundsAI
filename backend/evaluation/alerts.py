"""降级检测告警"""
import time
import threading
import logging

logger = logging.getLogger(__name__)


class DegradationAlerts:
    THRESHOLDS = {
        "mismatch_rate": 0.10,
        "p95_latency_ms": 5000,
        "rejection_rate": 0.30,
        "error_rate": 0.05,
    }

    def __init__(self, check_interval_sec: int = 300):
        self.check_interval_sec = check_interval_sec
        self._running = False

    def start(self):
        self._running = True
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()
        logger.info(f"DegradationAlerts started, check every {self.check_interval_sec}s")

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            self.check()
            time.sleep(self.check_interval_sec)

    def check(self):
        try:
            from backend.db.mysql_store import get_conn
            conn = get_conn()
        except Exception:
            return
        try:
            sql = """SELECT SUM(CASE WHEN fatal_errors > 0 THEN 1 ELSE 0 END) / COUNT(*) AS error_rate
                     FROM evaluation_records
                     WHERE created_at >= NOW() - INTERVAL 30 MINUTE"""
            with conn.cursor() as cur:
                cur.execute(sql)
                row = cur.fetchone()
            if row and row[0]:
                rate = float(row[0])
                if rate > self.THRESHOLDS["error_rate"]:
                    from backend.event_bus import bus
                    bus.publish("evaluation.degraded", metric="error_rate",
                                current=rate, threshold=self.THRESHOLDS["error_rate"])
                    logger.warning(f"Quality degradation: error_rate={rate:.2%}")
        except Exception:
            pass
        finally:
            conn.close()


alerts = DegradationAlerts()
