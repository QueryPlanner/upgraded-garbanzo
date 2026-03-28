# Git Commit Message Rules

Always plan the message title and body before creating a git commit. Follow the steps below.

### Step 1 - Plan the Commit Message Title

- Commit titles MUST be 50 characters or less **TOTAL** (e.g., "fix: " counts as 5 characters toward the 50 character limit, "ci: " counts as 4, etc.)
- Use one of the Conventional Commits style title prefix tags: "build", "chore", "ci", "docs", "feat", "fix", "perf", "style", "refactor", "test"
- Write titles in imperative voice (e.g., "Add feature", "Fix bug", "Update docs")
- Plan the title first and then count the number of characters in it using the Bash tool
- Example: for the message "fix: add default model for agents" run `echo -n "fix: add default model for agents" | wc -c` and read the resulting number of characters
- Refine the commit message title until it's 50 characters or less, then continue to Step 2 to complete the commit message

### Step 2 - Complete the Commit Message

- **MUST include a blank line** between the title and body
- Write commit message bodies in list format with dashes (e.g., "- Update the README file")
- Write body items in imperative voice (e.g., "Add feature", "Fix bug", "Update docs")
- Limit each body item to 72 characters total (including the dash and spaces)
- **IMPORTANT**: Do NOT use PR formatting (## What/Why/How) in commit messages

# GitHub Issue Rules

- Always add a Priority and a Level of Effort estimate to github issues
- Always run `gh label list` and add an appropriate label from the existing labels available in the repository
- Always create a `Sources` section that includes verified documentation URLs, examples, file links, etc. to support issue contents
- Always include **passing criteria** (or **definition of done**) that state how to
  verify the issue is fully resolved **without relying on user interaction**—for
  example: specific automated tests or test commands that must pass, lint/type
  checks, API contracts or fixtures, log or metric assertions, or scripted
  reproduction steps an implementer can run end-to-end. Criteria should be
  concrete enough that a reviewer or CI can confirm closure objectively.

# Pull Request Rules

- Use Conventional Commits style for PR titles
- Structure PR descriptions with these sections using "##" 2nd-level markdown format:
  - **## What**: Brief description of the change
  - **## Why**: Motive or reason for the pull request
  - **## How**: Bulleted list of specific modifications
  - **## Tests**: How changes were verified (with checkboxes)
- Optionally include these headings where appropriate:
  - **## Breaking Changes**: Include when appropriate for compatibility issues
  - **## Related Issues**: ALWAYS reference related issues (e.g., "Closes #123", "Fixes #123", or "Resolves #123")
- Do not bold the actual markdown headings in PR messages (bolding shown above is for emphasis in this file only)
- **IMPORTANT**: Only use this formatting for PRs, NOT for commit messages

# Release Workflow Rules

## Overview

Two-phase workflow for version bumps, branch tags, and creating and publishing releases using semantic versioning:

1. **Prepare Release** - Create feature branch with version bump and updated CHANGELOG
2. **Tag Release** - After PR merge, create and push git tag on main

## When User Requests a Release

When the user indicates they want to cut a release, use the appropriate agent to:

- Review changes since last release
- Recommend version bump (MAJOR/MINOR/PATCH based on semantic versioning)
- Prepare release PR on feature branch

**Don't ask permission** - proactively delegate to an agent when release is requested.

## Phase 1: Prepare Release (Feature Branch)

Delegate to the agent to:

- Update version files (**IMPORTANT:** follow language-specific version bump workflow rules)
- Update `CHANGELOG.md` using the "Keep A Changelog" format:
  - Convert [Unreleased] to [X.Y.Z] - YYYY-MM-DD
  - Add new empty [Unreleased] section with no subheadings
  - Update version comparison links after verifying the remote config using `git remote -v `
- Create feature branch (e.g., `release/v0.9.0`)
- Create commit with version bump
- Push branch to remote
- Create pull request

After PR is created, remind user to review and merge.

## Phase 2: Tag Release (Main Branch)

After user confirms release PR is merged, delegate to the agent to:

- Switch to main and pull latest
- Verify on main and up-to-date
- Create annotated git tag (e.g., `v0.9.0`) with release summary
- Push tag to remote: `git push origin vX.Y.Z`

## Verification

After the agent completes tagging, verify:

- Tag exists locally: `git tag --list | grep vX.Y.Z`
- Tag pushed to remote: `git ls-remote --tags origin | grep vX.Y.Z`

## Semantic Versioning

Recommend version bump based on changes:

**MAJOR (X.0.0)**

- Breaking changes in 1.x.x+ versions
- API changes that break backward compatibility
- Removal of deprecated features

**MINOR (0.X.0)**

- New features (backward compatible)
- Breaking changes in 0.x.x versions (pre-1.0)
- Significant enhancements

**PATCH (0.0.X)**

- Bug fixes
- Documentation updates
- Performance improvements (no API changes)
