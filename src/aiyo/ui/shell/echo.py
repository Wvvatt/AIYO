"""Echo rendering for user input display."""

from __future__ import annotations

from rich.text import Text

# Use a simple prompt symbol
PROMPT_SYMBOL = "✨"


def render_user_echo_text(text: str) -> Text:
    """Render the local prompt text exactly as the user saw it in the buffer."""
    return Text(f"{PROMPT_SYMBOL} {text}")
