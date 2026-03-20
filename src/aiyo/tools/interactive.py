"""Interactive tools for user interaction."""

from dataclasses import dataclass

from aiyo.tools.exceptions import ToolError


@dataclass
class Option:
    """A single option for a question."""

    label: str
    description: str | None = None
    preview: str | None = None


@dataclass
class Question:
    """A question to ask the user."""

    question: str
    header: str | None = None
    options: list[Option] | None = None
    multi_select: bool = False


def _validate_questions(questions: list[Question]) -> None:
    """Validate questions parameter.

    Args:
        questions: List of questions to validate.

    Raises:
        ToolError: If questions is invalid.
    """
    if not isinstance(questions, list):
        raise ToolError(f"questions must be a list, got {type(questions).__name__}")

    if len(questions) < 1 or len(questions) > 4:
        raise ToolError(f"questions must contain 1-4 items, got {len(questions)}")

    for idx, q in enumerate(questions):
        if not isinstance(q, dict):
            raise ToolError(f"question {idx} must be a dict, got {type(q).__name__}")

        # Validate question text
        question_text = q.get("question")
        if not question_text:
            raise ToolError(f"question {idx}: 'question' field is required")
        if not isinstance(question_text, str):
            raise ToolError(f"question {idx}: 'question' must be a string")
        if not question_text.strip().endswith("?"):
            # Auto-append question mark if missing
            q["question"] = question_text.strip() + "?"

        # Validate options if provided
        options = q.get("options")
        if options is not None:
            if not isinstance(options, list):
                raise ToolError(f"question {idx}: 'options' must be a list")
            if len(options) < 2 or len(options) > 4:
                raise ToolError(
                    f"question {idx}: 'options' must contain 2-4 items, got {len(options)}"
                )

            for opt_idx, opt in enumerate(options):
                if not isinstance(opt, dict):
                    raise ToolError(f"question {idx}, option {opt_idx}: must be a dict")
                label = opt.get("label")
                if not label:
                    raise ToolError(f"question {idx}, option {opt_idx}: 'label' is required")
                if not isinstance(label, str):
                    raise ToolError(f"question {idx}, option {opt_idx}: 'label' must be a string")


async def ask_user_question(questions: list[Question]) -> str:
    """Ask the user questions during execution and collect their answers.

    Use this tool when you need to:
    1. Gather user preferences or requirements
    2. Clarify ambiguous instructions
    3. Get decisions on implementation choices as you work
    4. Offer choices to the user about what direction to take

    Usage notes:
    - Users will always be able to select "Other" to provide custom text input
    - Use multi_select: true to allow multiple answers to be selected for a question
    - If you recommend a specific option, make that the first option in the list
      and add "(Recommended)" at the end of the label

    Plan mode note: In plan mode, use this tool to clarify requirements or choose
    between approaches BEFORE finalizing your plan. Do NOT use this tool to ask
    "Is my plan ready?" or "Should I proceed?" - use ExitPlanMode for plan approval.
    IMPORTANT: Do not reference "the plan" in your questions (e.g., "Do you have
    feedback about the plan?", "Does the plan look good?") because the user cannot
    see the plan in the UI until you call ExitPlanMode. If you need plan approval,
    use ExitPlanMode instead.

    Preview feature:
    Use the optional `preview` field on options when presenting concrete artifacts
    that users need to visually compare:
    - ASCII mockups of UI layouts or components
    - Code snippets showing different implementations
    - Diagram variations
    - Configuration examples

    Preview content is rendered as markdown in a monospace box. Multi-line text
    with newlines is supported. When any option has a preview, the UI switches to
    a side-by-side layout with a vertical option list on the left and preview on
    the right. Do not use previews for simple preference questions where labels
    and descriptions suffice. Note: previews are only supported for single-select
    questions (not multi_select).

    Args:
        questions: Questions to ask the user (1-4 questions). Each Question has:
            - question: The complete question text.
            - header: Very short label displayed as a chip/tag (max 12 chars).
            - options: List of Option objects (2-4 items), each with:
                - label: Display text (1-5 words).
                - description: Explanation of what this option means.
                - preview: Optional preview content (code snippets, mockups, etc.).
            - multi_select: Set to true to allow multiple options selection.

    Returns:
        A message indicating that the agent should stop calling tools and wait
        for the user to respond. Interactive UIs will intercept this and prompt
        the user for input.

    Raises:
        ToolError: If questions parameter is invalid.
    """
    _validate_questions(questions)
    return "Please stop calling tools loop and wait for the user input."
