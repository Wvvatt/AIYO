"""Signal handling utilities."""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Callable


def install_sigint_handler(
    loop: asyncio.AbstractEventLoop, 
    handler: Callable[[], None]
) -> Callable[[], None]:
    """Install a SIGINT handler and return a function to remove it."""
    
    def _signal_handler():
        handler()
    
    # For asyncio, we use add_signal_handler on Unix
    try:
        loop.add_signal_handler(signal.SIGINT, _signal_handler)
        
        def remove():
            try:
                loop.remove_signal_handler(signal.SIGINT)
            except (NotImplementedError, ValueError):
                pass
        
        return remove
    except NotImplementedError:
        # Windows doesn't support add_signal_handler
        return lambda: None
