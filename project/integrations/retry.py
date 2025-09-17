"""
Mecanism simplu de retry cu backoff exponențial.
Poate fi folosit ca decorator @retry sau ca funcție utilitară.
"""

import time
import functools
from typing import Callable, Type, Tuple

class RetryError(Exception):
    """Ridicat dacă toate încercările eșuează."""
    pass

def retry(
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    tries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    logger: Callable[[str], None] = print,
):
    """
    Decorator pentru retry.
    - exceptions: tipurile de excepții pe care să le prindă
    - tries: număr total de încercări
    - delay: întârziere inițială între încercări (secunde)
    - backoff: factor multiplicator pentru delay
    - logger: funcția de logging (default: print)
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            _tries, _delay = tries, delay
            last_exc = None
            while _tries > 0:
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    _tries -= 1
                    if _tries <= 0:
                        break
                    if logger:
                        logger(f"[retry] {func.__name__} failed ({e}), retrying in {_delay:.1f}s...")
                    time.sleep(_delay)
                    _delay *= backoff
            raise RetryError(f"{func.__name__} failed after {tries} tries") from last_exc
        return wrapper
    return decorator

# ----------------------------------------
# Exemplu de utilizare
# ----------------------------------------

if __name__ == "__main__":
    import random

    @retry(tries=4, delay=1, backoff=2)
    def flaky_task():
        if random.random() < 0.7:
            raise ValueError("Random fail")
        return "success"

    print(flaky_task())
