"""Todo list tool."""


class _TodoManager:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def update(self, items: list) -> str:
        if len(items) > 20:
            raise ValueError("Max 20 todos allowed")
        validated: list[dict] = []
        in_progress_count = 0
        for i, item in enumerate(items):
            text = str(item.get("text", "")).strip()
            status = str(item.get("status", "pending")).lower()
            item_id = str(item.get("id", str(i + 1)))
            if not text:
                raise ValueError(f"Item {item_id}: text required")
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Item {item_id}: invalid status '{status}'")
            if status == "in_progress":
                in_progress_count += 1
            validated.append({"id": item_id, "text": text, "status": status})
        if in_progress_count > 1:
            raise ValueError("Only one task can be in_progress at a time")
        self.items = validated
        return self._render()

    def _render(self) -> str:
        if not self.items:
            return "No todos."
        lines = []
        for item in self.items:
            marker = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}[item["status"]]
            lines.append(f"{marker} #{item['id']}: {item['text']}")
        done = sum(1 for t in self.items if t["status"] == "completed")
        lines.append(f"\n({done}/{len(self.items)} completed)")
        return "\n".join(lines)


_TODO = _TodoManager()


def todo(items: list) -> str:
    """Update the shared todo list with the full current state.

    Replace the entire todo list by passing all items (including unchanged ones).
    Each item must be a dict with keys:
      - "id": unique identifier string (e.g. "1", "2")
      - "text": task description (non-empty string)
      - "status": one of "pending", "in_progress", "completed"

    Rules:
      - At most 20 items.
      - At most one item may be "in_progress" at a time.

    Returns the rendered todo list as a string.

    Args:
        items: List of todo item dicts representing the complete new state.
    """
    try:
        return _TODO.update(items)
    except ValueError as e:
        return f"Error: {e}"
