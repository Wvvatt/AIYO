"""Tests for interactive tools."""

import pytest

from aiyo.tools.exceptions import ToolError
from aiyo.tools.interactive import (
    Option,
    Question,
    _validate_questions,
    ask_user,
)


class TestValidateQuestions:
    """Tests for _validate_questions function."""

    def test_valid_single_question(self):
        """Test validation passes with a single valid question."""
        questions = [
            {"question": "What is your name?"},
        ]
        # Should not raise
        _validate_questions(questions)

    def test_valid_question_with_options(self):
        """Test validation passes with question and options."""
        questions = [
            {
                "question": "Which approach?",
                "header": "Approach",
                "options": [
                    {"label": "Simple", "description": "Quick"},
                    {"label": "Advanced", "description": "Full featured"},
                ],
                "multi_select": False,
            }
        ]
        # Should not raise
        _validate_questions(questions)

    def test_valid_multiple_questions(self):
        """Test validation passes with multiple questions (up to 4)."""
        questions = [
            {"question": "Question 1?"},
            {"question": "Question 2?"},
            {"question": "Question 3?"},
            {"question": "Question 4?"},
        ]
        # Should not raise
        _validate_questions(questions)

    def test_empty_list_raises_error(self):
        """Test empty questions list raises ToolError."""
        with pytest.raises(ToolError, match="questions must contain 1-4 items, got 0"):
            _validate_questions([])

    def test_too_many_questions_raises_error(self):
        """Test more than 4 questions raises ToolError."""
        questions = [
            {"question": "Q1?"},
            {"question": "Q2?"},
            {"question": "Q3?"},
            {"question": "Q4?"},
            {"question": "Q5?"},
        ]
        with pytest.raises(ToolError, match="questions must contain 1-4 items, got 5"):
            _validate_questions(questions)

    def test_non_list_raises_error(self):
        """Test non-list input raises ToolError."""
        with pytest.raises(ToolError, match="questions must be a list"):
            _validate_questions("not a list")

    def test_non_dict_question_raises_error(self):
        """Test non-dict question raises ToolError."""
        questions = ["not a dict"]
        with pytest.raises(ToolError, match="question 0 must be a dict"):
            _validate_questions(questions)

    def test_missing_question_field_raises_error(self):
        """Test missing question field raises ToolError."""
        questions = [{"header": "Test"}]
        with pytest.raises(ToolError, match="question 0: 'question' field is required"):
            _validate_questions(questions)

    def test_empty_question_raises_error(self):
        """Test empty question text raises ToolError."""
        questions = [{"question": ""}]
        with pytest.raises(ToolError, match="question 0: 'question' field is required"):
            _validate_questions(questions)

    def test_non_string_question_raises_error(self):
        """Test non-string question raises ToolError."""
        questions = [{"question": 123}]
        with pytest.raises(ToolError, match="question 0: 'question' must be a string"):
            _validate_questions(questions)

    def test_missing_question_mark_raises_error(self):
        """Test question without question mark is auto-fixed."""
        questions = [{"question": "What is your name"}]
        _validate_questions(questions)
        assert questions[0]["question"] == "What is your name?"

    def test_non_list_options_raises_error(self):
        """Test non-list options raises ToolError."""
        questions = [{"question": "Test?", "options": "not a list"}]
        with pytest.raises(ToolError, match="question 0: 'options' must be a list"):
            _validate_questions(questions)

    def test_too_few_options_raises_error(self):
        """Test less than 2 options raises ToolError."""
        questions = [{"question": "Test?", "options": [{"label": "Only one"}]}]
        with pytest.raises(ToolError, match="question 0: 'options' must contain 2-4 items, got 1"):
            _validate_questions(questions)

    def test_too_many_options_raises_error(self):
        """Test more than 4 options raises ToolError."""
        questions = [
            {
                "question": "Test?",
                "options": [
                    {"label": "A"},
                    {"label": "B"},
                    {"label": "C"},
                    {"label": "D"},
                    {"label": "E"},
                ],
            }
        ]
        with pytest.raises(ToolError, match="question 0: 'options' must contain 2-4 items, got 5"):
            _validate_questions(questions)

    def test_non_dict_option_raises_error(self):
        """Test non-dict option raises ToolError."""
        questions = [{"question": "Test?", "options": ["not a dict", {"label": "Valid"}]}]
        with pytest.raises(ToolError, match="question 0, option 0: must be a dict"):
            _validate_questions(questions)

    def test_missing_option_label_raises_error(self):
        """Test missing option label raises ToolError."""
        questions = [
            {"question": "Test?", "options": [{"description": "No label"}, {"label": "Valid"}]}
        ]
        with pytest.raises(ToolError, match="question 0, option 0: 'label' is required"):
            _validate_questions(questions)

    def test_non_string_option_label_raises_error(self):
        """Test non-string option label raises ToolError."""
        questions = [{"question": "Test?", "options": [{"label": 123}, {"label": "Valid"}]}]
        with pytest.raises(ToolError, match="question 0, option 0: 'label' must be a string"):
            _validate_questions(questions)


class TestAskUserQuestion:
    """Tests for ask_user function."""

    @pytest.mark.asyncio
    async def test_returns_pending_message(self):
        """Test function returns pending message for valid input."""
        questions = [{"question": "What is your name?"}]
        result = await ask_user(questions)

        assert result == "Please stop calling tools loop and wait for the user input."

    @pytest.mark.asyncio
    async def test_validates_questions(self):
        """Test function validates questions and raises ToolError."""
        with pytest.raises(ToolError):
            await ask_user([])

    @pytest.mark.asyncio
    async def test_accepts_question_dict(self):
        """Test function works with question dicts."""
        questions = [
            {
                "question": "Which approach?",
                "header": "Approach",
                "options": [
                    {"label": "Simple", "description": "Quick"},
                    {"label": "Advanced"},
                ],
                "multi_select": False,
            }
        ]
        result = await ask_user(questions)
        assert "Please stop calling tools" in result


class TestDataclasses:
    """Tests for Option and Question dataclasses."""

    def test_option_defaults(self):
        """Test Option dataclass has correct defaults."""
        opt = Option(label="Test")
        assert opt.label == "Test"
        assert opt.description is None
        assert opt.preview is None

    def test_option_with_values(self):
        """Test Option dataclass accepts all values."""
        opt = Option(
            label="Test",
            description="A test option",
            preview="```python\nprint('hello')\n```",
        )
        assert opt.label == "Test"
        assert opt.description == "A test option"
        assert "print('hello')" in opt.preview

    def test_question_defaults(self):
        """Test Question dataclass has correct defaults."""
        q = Question(question="What?")
        assert q.question == "What?"
        assert q.header is None
        assert q.options is None
        assert q.multi_select is False

    def test_question_with_options(self):
        """Test Question dataclass with options."""
        q = Question(
            question="Which?",
            header="Choice",
            options=[
                Option(label="A"),
                Option(label="B", description="Option B"),
            ],
            multi_select=True,
        )
        assert q.question == "Which?"
        assert q.header == "Choice"
        assert len(q.options) == 2
        assert q.multi_select is True
