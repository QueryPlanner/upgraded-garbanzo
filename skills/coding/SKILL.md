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
User requests coding task -> You work on it -> PR created (if applicable)
```

## Claude Code Integration

Claude Code is integrated via the `run_claude_coding_task` tool. This is an asynchronous, long-running tool that will free you up to do other tasks while Claude Code autonomously implements the requested changes.

### Required Environment Variables

The `run_claude_coding_task` tool automatically injects `ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN` from your environment. **You do not need to manually export these.**

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

Use the `run_claude_coding_task` tool with a structured prompt. This tool will run asynchronously and can take 20-30 minutes. The framework will return a pending status to you and notify you once it completes.

**Example usage of `run_claude_coding_task`:**
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

### Step 4: Review Changes (Once the Tool Completes)

When the `run_claude_coding_task` returns its output asynchronously, check what was done:

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
If tests fail, you can call `run_claude_coding_task` again with a prompt like:
`"Tests are failing with: <error>. Fix the tests."`

## Status Updates to User

After completing (or failing) the work, send a summary:

1. **What issue**: Issue #X - Title
2. **What was done**: Summary of changes
3. **PR link**: URL to the created PR (or "pending review" if not created)
4. **Any blockers**: Issues encountered that need user attention

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
6. *Wait for the async tool to return*
7. Review the changes
8. Push and create PR
9. Send summary: "Issue #42 complete! PR created: <url>"
