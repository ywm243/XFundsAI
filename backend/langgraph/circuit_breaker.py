"""熔断器 — 连续失败后短路，返回降级结果"""
import time
import asyncio
import logging

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """包装外部依赖，连续失败后短路返回降级结果

    States: CLOSED(正常) -> OPEN(短路) -> HALF_OPEN(探测) -> CLOSED(恢复)
    """

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

    def __init__(self, name: str, failure_threshold: int = 5,
                 reset_timeout: float = 60.0, fallback_fn=None):
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.fallback_fn = fallback_fn
        self.state = self.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0.0

    async def call(self, fn, *args, **kwargs):
        if self.state == self.OPEN:
            if time.time() - self.last_failure_time > self.reset_timeout:
                self.state = self.HALF_OPEN
                logger.info(f"CircuitBreaker {self.name} -> HALF_OPEN (probing)")
            else:
                logger.warning(f"CircuitBreaker {self.name} OPEN, using fallback")
                if self.fallback_fn:
                    return await self._invoke(self.fallback_fn, *args, **kwargs)
                return None

        try:
            result = await self._invoke(fn, *args, **kwargs)
            if self.state == self.HALF_OPEN:
                self.state = self.CLOSED
                logger.info(f"CircuitBreaker {self.name} -> CLOSED (recovered)")
            self.failure_count = 0
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.state = self.OPEN
                logger.error(
                    f"CircuitBreaker {self.name} -> OPEN ({self.failure_count} failures): {e}"
                )
            if self.fallback_fn:
                return await self._invoke(self.fallback_fn, *args, **kwargs)
            raise

    async def _invoke(self, fn, *args, **kwargs):
        if asyncio.iscoroutinefunction(fn):
            return await fn(*args, **kwargs)
        return fn(*args, **kwargs)

    def reset(self):
        self.state = self.CLOSED
        self.failure_count = 0
