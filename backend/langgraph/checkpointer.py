"""MySQL Checkpointer for LangGraph — 节点执行后自动持久化 AgentState"""
import json
import uuid
import logging
from langgraph.checkpoint.base import BaseCheckpointSaver

logger = logging.getLogger(__name__)


class MySqlCheckpointer(BaseCheckpointSaver):
    """LangGraph checkpointer 实现，持久化到 MySQL"""

    def __init__(self):
        super().__init__()
        self._conn = None

    def _get_conn(self):
        if self._conn is None:
            from db.mysql_store import get_conn
            self._conn = get_conn()
        return self._conn

    def put(self, config: dict, checkpoint: dict, metadata: dict,
            new_versions: dict) -> dict:
        """持久化一个 checkpoint"""
        thread_id = config.get("configurable", {}).get("thread_id", "default")
        checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")
        checkpoint_id = checkpoint.get("id") or str(uuid.uuid4())
        parent_id = checkpoint.get("parent_checkpoint_id", "")

        data = json.dumps(checkpoint, ensure_ascii=False, default=str)
        conn = self._get_conn()
        sql = """INSERT INTO langgraph_checkpoints
                 (thread_id, checkpoint_ns, checkpoint_id, parent_id, data)
                 VALUES (%s, %s, %s, %s, %s)"""
        with conn.cursor() as cur:
            cur.execute(sql, (thread_id, checkpoint_ns, checkpoint_id, parent_id, data))
        conn.commit()
        logger.debug(f"Checkpoint saved: {thread_id}/{checkpoint_id}")
        return {"config": config, "checkpoint": checkpoint}

    def get(self, config: dict) -> dict | None:
        """获取最新 checkpoint"""
        thread_id = config.get("configurable", {}).get("thread_id", "default")
        checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")
        conn = self._get_conn()
        sql = """SELECT data FROM langgraph_checkpoints
                 WHERE thread_id = %s AND checkpoint_ns = %s
                 ORDER BY created_at DESC LIMIT 1"""
        with conn.cursor() as cur:
            cur.execute(sql, (thread_id, checkpoint_ns))
            row = cur.fetchone()
        if not row:
            return None
        data = row["data"] if isinstance(row, dict) else row[0]
        if isinstance(data, str):
            return json.loads(data)
        return data

    def get_tuple(self, config: dict) -> tuple | None:
        return self.get(config)

    async def aget_tuple(self, config: dict) -> tuple | None:
        return self.get_tuple(config)
