"""Tests for skills loader module."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.skills.loader import (
    DEFAULT_SKILLS_DIR,
    SkillParseError,
    create_skill_toolset,
    get_available_skills,
    parse_skill_file,
)


@pytest.fixture
def temp_skills_dir() -> Path:
    """Create a temporary skills directory with a valid skill."""
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_path = Path(tmpdir)
        skill_dir = skills_path / "test-skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            """---
name: test-skill
description: A test skill for unit testing
---

# Test Skill Instructions

This is the body of the test skill.
It contains instructions for the agent.
"""
        )
        yield skills_path


@pytest.fixture
def invalid_skill_dir() -> Path:
    """Create a temporary skills directory with an invalid skill."""
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_path = Path(tmpdir)
        skill_dir = skills_path / "invalid-skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            """This is not valid markdown - missing frontmatter
"""
        )
        yield skills_path


@pytest.fixture
def missing_fields_skill_dir() -> Path:
    """Create a skill with missing required fields."""
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_path = Path(tmpdir)
        skill_dir = skills_path / "incomplete-skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            """---
name: incomplete
---

Missing description field.
"""
        )
        yield skills_path


class TestParseSkillFile:
    """Tests for parse_skill_file function."""

    def test_parse_valid_skill(self, temp_skills_dir: Path) -> None:
        """Test parsing a valid skill file."""
        skill_file = temp_skills_dir / "test-skill" / "SKILL.md"
        skill = parse_skill_file(skill_file)

        assert skill.frontmatter.name == "test-skill"
        assert skill.frontmatter.description == "A test skill for unit testing"
        assert "Test Skill Instructions" in skill.instructions

    def test_parse_nonexistent_file(self) -> None:
        """Test parsing a nonexistent file."""
        with pytest.raises(SkillParseError) as exc_info:
            parse_skill_file(Path("/nonexistent/SKILL.md"))

        assert "not found" in str(exc_info.value)

    def test_parse_invalid_frontmatter(self, invalid_skill_dir: Path) -> None:
        """Test parsing a file with invalid frontmatter."""
        skill_file = invalid_skill_dir / "invalid-skill" / "SKILL.md"

        with pytest.raises(SkillParseError) as exc_info:
            parse_skill_file(skill_file)

        assert "Invalid SKILL.md format" in str(exc_info.value)

    def test_parse_missing_required_fields(
        self, missing_fields_skill_dir: Path
    ) -> None:
        """Test parsing a file missing required fields."""
        skill_file = missing_fields_skill_dir / "incomplete-skill" / "SKILL.md"

        with pytest.raises(SkillParseError) as exc_info:
            parse_skill_file(skill_file)

        assert "Missing" in str(exc_info.value)


class TestGetAvailableSkills:
    """Tests for get_available_skills function."""

    def test_get_skills_from_directory(self, temp_skills_dir: Path) -> None:
        """Test retrieving skills from a directory."""
        skills = get_available_skills(temp_skills_dir)

        assert len(skills) == 1
        assert skills[0].frontmatter.name == "test-skill"

    def test_get_skills_empty_directory(self) -> None:
        """Test retrieving skills from an empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skills = get_available_skills(Path(tmpdir))
            assert skills == []

    def test_get_skills_nonexistent_directory(self) -> None:
        """Test retrieving skills from a nonexistent directory."""
        with patch("agent.skills.loader.logger") as mock_logger:
            skills = get_available_skills(Path("/nonexistent/skills"))

            assert skills == []
            mock_logger.warning.assert_called_once()

    def test_get_skills_skips_files(self, temp_skills_dir: Path) -> None:
        """Test that non-directory files are skipped."""
        # Create a file in the skills directory
        (temp_skills_dir / "not-a-directory.md").write_text("content")

        skills = get_available_skills(temp_skills_dir)

        assert len(skills) == 1  # Only the directory-based skill


class TestCreateSkillToolset:
    """Tests for create_skill_toolset function."""

    def test_create_toolset_with_skills(self, temp_skills_dir: Path) -> None:
        """Test creating a toolset with skills."""
        toolset = create_skill_toolset(temp_skills_dir)

        assert toolset is not None

    def test_create_toolset_empty_directory(self) -> None:
        """Test creating a toolset from an empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("agent.skills.loader.logger") as mock_logger:
                toolset = create_skill_toolset(Path(tmpdir))

                assert toolset is not None
                mock_logger.warning.assert_called_once()


class TestDefaultSkillsDir:
    """Tests for the default skills directory."""

    def test_default_skills_dir_path(self) -> None:
        """Test that the default skills dir is correctly set."""
        # The default should be at project root/skills
        assert DEFAULT_SKILLS_DIR.name == "skills"
        assert "upgraded-garbanzo" in str(DEFAULT_SKILLS_DIR)
