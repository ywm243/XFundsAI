"""统一重试层 — 对瞬态错误自动重试"""
import asyncio
import logging

logger = logging.getLogger(__name__)

RETRYABLE_ERRORS = (
    ConnectionError,
    TimeoutError,
    OSError,
)


class RetryableNode:
    """包装 LangGraph 节点函数，对瞬态错误自动重试

    非瞬态错误（ValueError, TypeError, 业务逻辑错误）不重试，直接抛出
    """

    def __init__(self, fn, max_retries: int = 2, backoff_base: float = 1.0):
        self.fn = fn
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.__name__ = getattr(fn, "__name__", "retryable")

    async def __call__(self, *args, **kwargs):
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                if asyncio.iscoroutinefunction(self.fn):
                    return await self.fn(*args, **kwargs)
                return self.fn(*args, **kwargs)
            except RETRYABLE_ERRORS as e:
                last_error = e
                if attempt < self.max_retries:
                    wait = self.backoff_base * (2 ** attempt)
                    logger.warning(
                        f"RetryableNode {self.__name__} attempt {attempt + 1}/{self.max_retries + 1} "
                        f"failed with {type(e).__name__}, retrying in {wait:.1f}s"
                    )
                    await asyncio.sleep(wait)
        logger.error(
            f"RetryableNode {self.__name__} exhausted all {self.max_retries + 1} attempts: {last_error}"
        )
        raise last_error


def retryable(max_retries: int = 2, backoff_base: float = 1.0):
    """装饰器：将函数包装为可重试"""
    def decorator(fn):
        return RetryableNode(fn, max_retries=max_retries, backoff_base=backoff_base)
    return decorator
