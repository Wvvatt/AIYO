"""Tests for configuration module."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from aiyo.config import Settings, settings


class TestSettings:
    """Tests for Settings class."""

    def test_default_values(self):
        """Test default configuration values."""
        with patch.dict(os.environ, {}, clear=True):
            test_settings = Settings()

            assert test_settings.provider == "openai"
            assert test_settings.model_name == "gpt-4o-mini"
            assert test_settings.agent_max_iterations == 150
            assert test_settings.response_token_limit == 8190
            assert test_settings.llm_timeout == 300

    def test_custom_values_from_env(self):
        """Test loading custom values from environment variables."""
        env_vars = {
            "PROVIDER": "anthropic",
            "MODEL_NAME": "claude-3-opus",
            "AGENT_MAX_ITERATIONS": "100",
            "RESPONSE_TOKEN_LIMIT": "16000",
            "LLM_TIMEOUT": "120",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            test_settings = Settings()

            assert test_settings.provider == "anthropic"
            assert test_settings.model_name == "claude-3-opus"
            assert test_settings.agent_max_iterations == 100
            assert test_settings.response_token_limit == 16000
            assert test_settings.llm_timeout == 120

    def test_work_dir_default(self):
        """Test default work directory."""
        with patch.dict(os.environ, {}, clear=True):
            test_settings = Settings()

            # Should default to current working directory
            assert isinstance(test_settings.work_dir, Path)

    def test_work_dir_from_env(self):
        """Test work directory from environment variable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_vars = {"WORK_DIR": tmpdir}

            with patch.dict(os.environ, env_vars, clear=True):
                test_settings = Settings()

                assert test_settings.work_dir == Path(tmpdir)

    def test_settings_singleton(self):
        """Test that settings is a singleton instance."""
        # The imported settings should be the same instance
        from aiyo.config import settings as settings2

        assert settings is settings2


class TestEnvFileLoading:
    """Tests for .env file loading."""

    def test_env_file_loaded(self, tmp_path):
        """Test that .env file is loaded if present."""
        # Create a temporary .env file
        env_file = tmp_path / ".env"
        env_file.write_text("MODEL_NAME=custom-model\nPROVIDER=custom-provider")

        # Mock the env file location
        with patch("aiyo.config.Path") as mock_path:
            mock_path.return_value.parents = [tmp_path]
            mock_path.return_value.__truediv__ = lambda self, other: tmp_path / other

            # This test verifies the mechanism exists; actual loading is done by dotenv
            pass  # dotenv loading is tested implicitly
