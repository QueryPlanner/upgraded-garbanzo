"""Skill loader for parsing SKILL.md files and creating ADK Skills.

This module provides lazy-loading of skills from markdown files with YAML
frontmatter. Skills are only loaded when explicitly invoked by the agent,
saving tokens compared to always-included instructions.
"""

import logging
import re
from pathlib import Path

import yaml
from google.adk.tools.skill_toolset import SkillToolset, models

logger = logging.getLogger(__name__)

# Default skills directory at project root
DEFAULT_SKILLS_DIR = Path(__file__).parent.parent.parent.parent / "skills"


class SkillParseError(Exception):
    """Error parsing a SKILL.md file."""

    pass


def parse_skill_file(skill_path: Path) -> models.Skill:
    """Parse a SKILL.md file and create a Skill object.

    The SKILL.md file format uses YAML frontmatter followed by markdown:

    ```markdown
    ---
    name: skill-name
    description: Brief description of the skill
    ---

    # Skill Instructions

    Detailed markdown content with instructions for the agent...
    ```

    Args:
        skill_path: Path to the SKILL.md file.

    Returns:
        A Skill object configured from the file.

    Raises:
        SkillParseError: If the file cannot be parsed.
    """
    if not skill_path.exists():
        raise SkillParseError(f"Skill file not found: {skill_path}")

    content = skill_path.read_text()

    # Parse YAML frontmatter
    frontmatter_match = re.match(r"^---\n(.*?)\n---\n(.*)$", content, re.DOTALL)
    if not frontmatter_match:
        raise SkillParseError(
            f"Invalid SKILL.md format: {skill_path}. "
            "Expected YAML frontmatter between --- markers."
        )

    frontmatter_yaml = frontmatter_match.group(1)
    body = frontmatter_match.group(2).strip()

    try:
        fm_data = yaml.safe_load(frontmatter_yaml)
    except yaml.YAMLError as e:
        raise SkillParseError(f"Invalid YAML in {skill_path}: {e}") from e

    # Validate required fields
    if "name" not in fm_data:
        raise SkillParseError(f"Missing 'name' in {skill_path}")
    if "description" not in fm_data:
        raise SkillParseError(f"Missing 'description' in {skill_path}")

    # Create Frontmatter object
    frontmatter = models.Frontmatter(
        name=fm_data["name"],
        description=fm_data["description"],
        metadata=fm_data.get("metadata", {}),
    )

    logger.info(f"Loaded skill '{frontmatter.name}' from {skill_path}")

    # Create and return Skill object
    return models.Skill(
        frontmatter=frontmatter,
        instructions=body,
    )


def get_available_skills(skills_dir: Path | None = None) -> list[models.Skill]:
    """Get all available skills from the skills directory.

    Scans the skills directory for subdirectories containing SKILL.md files.

    Args:
        skills_dir: Optional path to skills directory.
            Defaults to project_root/skills

    Returns:
        List of Skill objects found in the directory.
    """
    skills_path = skills_dir or DEFAULT_SKILLS_DIR
    skills: list[models.Skill] = []

    if not skills_path.exists():
        logger.warning(f"Skills directory not found: {skills_path}")
        return skills

    for skill_folder in skills_path.iterdir():
        if not skill_folder.is_dir():
            continue

        skill_file = skill_folder / "SKILL.md"
        if not skill_file.exists():
            logger.debug(f"No SKILL.md in {skill_folder}")
            continue

        try:
            skill = parse_skill_file(skill_file)
            skills.append(skill)
        except SkillParseError as e:
            logger.error(f"Failed to parse skill: {e}")

    logger.info(f"Found {len(skills)} skills in {skills_path}")
    return skills


def create_skill_toolset(skills_dir: Path | None = None) -> SkillToolset:
    """Create a SkillToolset with all available skills.

    This is the main entry point for registering skills with the agent.
    The toolset allows the agent to dynamically load skill instructions
    only when needed.

    Args:
        skills_dir: Optional path to skills directory.

    Returns:
        A SkillToolset containing all available skills.
    """
    skills = get_available_skills(skills_dir)

    if not skills:
        logger.warning("No skills found. SkillToolset will be empty.")

    toolset = SkillToolset(skills=skills)
    logger.info(f"Created SkillToolset with {len(skills)} skills")
    return toolset
