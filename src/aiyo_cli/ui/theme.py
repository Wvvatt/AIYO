"""UI theme and console configuration."""

from rich.console import Console
from rich.theme import Theme

_PALETTE = {
    "accent": "#00a8e8",  # tool names, inline code, welcome
    "muted": "#666666",  # system messages, dim text
    "error": "#ff5555",  # errors
    "heading": "bold",  # section headers
}

THEME = Theme(
    {
        "accent": _PALETTE["accent"],
        "tool": f"bold {_PALETTE['accent']}",
        "muted": _PALETTE["muted"],
        "error": _PALETTE["error"],
        "heading": _PALETTE["heading"],
        "markdown.code": f"bold {_PALETTE['accent']}",
    }
)

CODE_THEME = "monokai"
TOOL_SUMMARY_WIDTH = 120
SPINNER_TEXT = "[muted]Aiyo...[/muted]"

console = Console(theme=THEME, soft_wrap=True)


def format_tokens(n: int) -> str:
    """Format token count: 1234 -> '1.2k', 0 -> '0'."""
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def get_palette() -> dict[str, str]:
    """Get the color palette."""
    return _PALETTE.copy()
