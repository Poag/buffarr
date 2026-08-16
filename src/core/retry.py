import asyncio
import logging

log = logging.getLogger("retry")


async def retry(retries: int, func):
    """Call the zero-arg async `func`, retrying with exponential backoff
    (2, 4, 8, ... seconds) up to `retries` additional times after the first
    attempt. Re-raises the last error once all attempts are exhausted."""
    last_err = None
    for i in range(retries + 1):
        if last_err is not None:
            secs = 2**i
            log.info("Retry after %d seconds", secs)
            await asyncio.sleep(secs)
        try:
            return await func()
        except Exception as e:
            log.error("%s", e)
            last_err = e
    raise last_err
