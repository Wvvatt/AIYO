"""UI theme and console configuration."""

from rich.console import Console
from rich.theme import Theme

_PALETTE = {
    "accent": "#5fd7ff",  # tool names, inline code, welcome
    "muted": "#666666",  # system messages, dim text
    "error": "#ff5555",  # errors
    "heading": "bold",  # section headers
}

THEME = Theme(
    {
        "tool": f"bold {_PALETTE['accent']}",
        "muted": _PALETTE["muted"],
        "error": _PALETTE["error"],
        "heading": _PALETTE["heading"],
        "markdown.code": f"bold {_PALETTE['accent']}",
    }
)

DIFF_THEME = "monokai"
SPINNER_TEXT = "[muted]Aiyo...[/muted]"

console = Console(theme=THEME)


def format_tokens(n: int) -> str:
    """Format token count: 1234 -> '1.2k', 0 -> '0'."""
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def get_palette() -> dict[str, str]:
    """Get the color palette."""
    return _PALETTE.copy()
