"""Per-conversation message accumulation with a configurable debounce timer.

When a message arrives :meth:`MessageBuffer.add_message` is called.  If no
further messages arrive for ``delay_seconds`` the accumulated text is joined
with ``\\n`` and forwarded to the ``on_flush`` callback for processing.  Each
new message within the waiting window resets the countdown, so a burst of
quickly typed messages is batched into a single agent call.

Thread-safety: the internal state is protected by a :class:`threading.Lock`.
``on_flush`` is invoked from the timer thread; it must be thread-safe itself.
"""

import logging
import threading
from collections import defaultdict
from typing import Callable

logger = logging.getLogger(__name__)


class MessageBuffer:
    """Accumulate messages per conversation and flush after a silence period.

    Args:
        delay_seconds: Seconds of silence required before the buffer is flushed.
            Defaults to 120 s (2 minutes), matching ``RESPONSE_DELAY_SECONDS``.
            Set to ``0`` to flush immediately (synchronous mode, useful in tests).
        on_flush: Callable that receives ``(conversation_id: int, text: str)``
            where *text* is all accumulated messages joined with ``\\n``.
    """

    def __init__(
        self,
        delay_seconds: float = 120.0,
        on_flush: Callable[[int, str], None] = lambda *_: None,
    ) -> None:
        self._delay = delay_seconds
        self._on_flush = on_flush
        self._lock = threading.Lock()
        self._buffers: dict[int, list[str]] = defaultdict(list)
        self._timers: dict[int, threading.Timer] = {}

    def add_message(self, conversation_id: int, text: str) -> None:
        """Append *text* to the buffer for *conversation_id* and reset the timer.

        If ``delay_seconds`` is 0 the message is flushed synchronously in the
        calling thread (useful for tests — pass ``delay_seconds=0`` explicitly
        to override the 120 s default).
        """
        with self._lock:
            self._buffers[conversation_id].append(text)
            existing = self._timers.pop(conversation_id, None)
            if existing is not None:
                existing.cancel()

            if self._delay <= 0:
                # Flush immediately — pop the buffer before releasing the lock
                # to avoid a concurrent timer racing with us.
                messages = self._buffers.pop(conversation_id, [])
            else:
                messages = None
                timer = threading.Timer(
                    self._delay, self._flush, args=[conversation_id]
                )
                self._timers[conversation_id] = timer
                timer.daemon = True
                timer.start()
                logger.debug(
                    "Buffered message for conversation %d (queued: %d); "
                    "timer set to %.1fs",
                    conversation_id,
                    len(self._buffers[conversation_id]),
                    self._delay,
                )

        if messages is not None:
            self._invoke_flush(conversation_id, messages)

    def _flush(self, conversation_id: int) -> None:
        """Timer callback: pop the buffer and invoke the flush handler."""
        with self._lock:
            messages = self._buffers.pop(conversation_id, [])
            self._timers.pop(conversation_id, None)

        if not messages:
            return

        logger.info(
            "Flushing %d buffered message(s) for conversation %d",
            len(messages),
            conversation_id,
        )
        self._invoke_flush(conversation_id, messages)

    def _invoke_flush(self, conversation_id: int, messages: list[str]) -> None:
        combined = "\n".join(messages)
        try:
            self._on_flush(conversation_id, combined)
        except Exception:
            logger.exception(
                "Error in flush callback for conversation %d", conversation_id
            )
