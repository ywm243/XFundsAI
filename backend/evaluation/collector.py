"""评估数据采集器 — 每次 LangGraph 执行完成后采集质量指标"""
import logging
import threading

logger = logging.getLogger(__name__)


class EvaluationCollector:
    def collect(self, state, duration_ms: float):
        mismatches = self._extract_mismatches(state)
        record = {
            "request_id": getattr(state, "request_id", ""),
            "session_id": getattr(state, "session_id", ""),
            "agent_type": (getattr(state, "router_decision", {}) or {}).get("agent", "BI"),
            "router_confidence": (getattr(state, "router_decision", {}) or {}).get("confidence", 0),
            "parse_confidence": (getattr(state, "parsed_params", {}) or {}).get("_confidence", 0),
            "post_validation_mismatches": mismatches,
            "sql_validated": getattr(state, "sql_validated", True),
            "validation_warnings_count": len(getattr(state, "validation_warnings", [])),
            "total_duration_ms": duration_ms,
            "wiki_hit": getattr(state, "wiki_hit", False),
            "errors_count": len(getattr(state, "errors", [])),
            "fatal_errors": len([e for e in getattr(state, "errors", [])
                                 if e.get("severity") == "fatal"]),
        }
        t = threading.Thread(target=_write_eval_async, args=(record,))
        t.daemon = True
        t.start()

    def _extract_mismatches(self, state) -> list:
        try:
            from agent.post_validator import PostValidator
            pv = PostValidator()
            mismatches = pv.validate(
                getattr(state, "summary", ""),
                getattr(state, "analysis_data", {}),
            )
            return [{"value": str(m[0]), "real": str(m[1])} for m in mismatches[:5]]
        except Exception:
            return []


def _write_eval_async(record: dict):
    try:
        from db.mysql_store import insert_evaluation_record
        insert_evaluation_record(record)
    except Exception:
        pass
