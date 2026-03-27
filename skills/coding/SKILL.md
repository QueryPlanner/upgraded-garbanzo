---
name: coding
description: Work on GitHub issues and create PRs using Claude Code
trigger_phrases:
  - "work on issue"
  - "fix issue"
  - "create pr for"
  - "code overnight"
  - "tackle issue"
  - "implement issue"
  - "write code"
  - "coding task"
---

# Coding Skill

You are the **coding assistant**. Users can ask you to work on GitHub issues, implement features,
fix bugs, or create PRs at any time.

## Workflow Overview

```
User requests coding task -> You work on it -> PR created -> CI checks verified
```

## Issue-to-PR Workflow

### Step 1: Fetch Issue Details

```bash
# Using GitHub CLI (gh must be authenticated)
gh issue view <issue_number> --json title,body,labels,repository
```

### Step 2: Prepare Workspace

**Always start from a clean state** to avoid residual files from previous branches:

```bash
# Navigate to repo
cd /home/app/garbanzo-home/workspace
git clone <repo_url> 2>/dev/null || cd <repo_name>

# IMPORTANT: Reset to clean state before starting
git checkout main
git fetch origin
git reset --hard origin/main  # Discard any local changes
git clean -fd                 # Remove untracked files/directories

# Clean up stale local branches (optional but recommended)
git branch --merged main | grep -v "^\* main$" | xargs -r git branch -d

# Now create fresh feature branch
git checkout -b issue-<number>-<short-description>
```

### Step 3: Delegate to Claude Code Tool

Use the `run_claude_coding_task` tool with a structured prompt.

**Example usage:**
```python
run_claude_coding_task(
    prompt="""
You are implementing GitHub issue #<number>.

Issue Title: <title>
Issue Body:
<issue_body>

Repository: <owner/repo>
Branch: issue-<number>-<short-description>

Requirements:
1. Read the codebase to understand the existing patterns
2. Implement the changes described in the issue
3. Write/update tests if applicable
4. Run tests to verify the changes work
5. Commit with a clear message following conventional commits
6. Do NOT push or create PR (I will review first)

Work autonomously. Use the tools available.
""",
    workdir="/home/app/garbanzo-home/workspace/<repo_name>"
)
```

### Step 4: Review Changes

Review the local changes before pushing:

```bash
# Check what was changed
git status
git diff main

# View the commit
git log -1 --stat
```

### Step 5: Push and Create PR

```bash
git push -u origin issue-<number>-<short-description>

gh pr create \
  --title "fix: <short description>" \
  --body "## What
<summary of changes>

## Why
Closes #<number>

## How
- <bullet list of changes>

## Tests
- [ ] <test checklist>

---
Implemented by Garbanzo"
```

### Step 6: Verify CI Validation Checks

Wait a couple of minutes after creating the PR, then check the PR CI validation checks.

```bash
gh pr checks
```

You do not need to verify the actual logic, just ensure the tests and CI checks pass. 
**If any checks fail, or if anything is missing, run the `run_claude_coding_task` tool again** to fix the issues. Repeat this verification step until all CI validation checks pass.

## Coding Practices & Best Practices

1. **Start from clean main** - Always `git reset --hard origin/main` and `git clean -fd` before creating a branch.
2. **Clean up stale branches** - Remove merged branches to keep the workspace tidy.
3. **Create descriptive branch names**: e.g., `issue-123-add-user-auth`.
4. **Keep commits atomic** and well-scoped.
5. **Run tests** locally before pushing, and ensure CI passes after pushing.
6. **Don't force push** - if something goes wrong, create a new branch or add a new commit.
7. **Never push directly to main** - always use feature branches.
8. **Don't merge your own PRs** - user reviews them.

## Error Handling

### Claude Code Fails

If `run_claude_coding_task` returns an error status:
- Read the provided `stdout` and `stderr` from the tool's result.
- Common issues: File not found (repo not cloned correctly), Timeout (task too complex).

### Tests Fail

```bash
# Run tests manually to see full output
npm test  # or pytest, cargo test, etc.
```
If tests fail locally or in CI, call `run_claude_coding_task` again with a prompt like:
`"Tests are failing with: <error>. Fix the tests."`

## Status Updates to User

After completing the workflow and verifying CI, send a summary:

1. **What issue**: Issue #X - Title
2. **What was done**: Summary of changes
3. **PR link**: URL to the created PR
4. **CI Status**: Confirmed passing checks
5. **Any blockers**: Issues encountered that need user attention

Store the status in memory for retrieval:

```bash
# Append to MEMORY.md
printf '\n## Coding Task - %s\n\n- **Issue**: #%d - %s\n- **Status**: %s\n- **PR**: %s\n- **Notes**: %s\n' \
  "$(date +%Y-%m-%d)" \
  "$issue_number" \
  "$issue_title" \
  "$status" \
  "$pr_url" \
  "$notes" \
  >> /app/memory/MEMORY.md
```

## Example Interactions

**User**: "Work on issue #42"

**Your response**:
1. Fetch issue #42 details
2. Clone/navigate to the repo
3. Reset to clean main: `git reset --hard origin/main && git clean -fd`
4. Create fresh branch `issue-42-<short-desc>`
5. Call `run_claude_coding_task`
6. Review the local changes
7. Push and create PR
8. Wait and verify CI checks pass (run Claude again if they fail)
9. Send summary: "Issue #42 complete! PR created: <url> and CI checks passed."