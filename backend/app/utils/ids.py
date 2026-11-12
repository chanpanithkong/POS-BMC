"""UUID version 7: time-ordered keys for business records (SRS 11.1).

Monotonic within a process (RFC 9562 section 6.2, method 1): the 12-bit rand_a
field holds a counter that increases within the same millisecond, so ids made
in a burst still sort in creation order and keep B-tree inserts sequential.
"""

import os
import threading
import time
import uuid

_lock = threading.Lock()
_last_ms = 0
_counter = 0


def uuid7() -> uuid.UUID:
    global _last_ms, _counter
    with _lock:
        unix_ms = time.time_ns() // 1_000_000
        if unix_ms > _last_ms:
            _last_ms, _counter = unix_ms, int.from_bytes(os.urandom(2), "big") & 0x3FF  # random start, leaves headroom
        else:
            _counter += 1
            if _counter > 0xFFF:  # counter exhausted: borrow the next millisecond
                _last_ms, _counter = _last_ms + 1, 0
        unix_ms, counter = _last_ms, _counter
    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    value = (unix_ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76  # version
    value |= counter << 64  # rand_a used as a counter
    value |= 0b10 << 62  # RFC 9562 variant
    value |= rand_b
    return uuid.UUID(int=value)
