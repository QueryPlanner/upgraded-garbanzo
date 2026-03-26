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

## Claude Code CLI Usage

Claude Code is installed in Docker. Use **non-interactive print mode** for automation.

### Required Environment Variables

Always export these before running Claude Code:

```bash
export ANTHROPIC_BASE_URL="http://0.0.0.0:4000"
export ANTHROPIC_AUTH_TOKEN="sk-1234567890"
```

### Required Flags

Always include these flags:
- `--model glm-5`: Use the configured model
- `--dangerously-skip-permissions`: Skip permission prompts for automation

### Print Mode (Recommended)

```bash
export ANTHROPIC_BASE_URL="http://0.0.0.0:4000"
export ANTHROPIC_AUTH_TOKEN="sk-1234567890"

claude -p "your prompt here" --output-format text --model glm-5 --dangerously-skip-permissions
```

This runs Claude Code non-interactively and returns output to stdout.

### Additional Flags

- `-p, --print`: Non-interactive mode (required for automation)
- `--output-format text|json`: Output format (default: text)
- `--max-tokens N`: Limit response length
- `--timeout N`: Timeout in seconds (use for long tasks)

### Background Execution

For long-running coding tasks, run in background:

```bash
# Export environment variables
export ANTHROPIC_BASE_URL="http://0.0.0.0:4000"
export ANTHROPIC_AUTH_TOKEN="sk-1234567890"

# Save output to a log file for later review
nohup claude -p "Fix issue #123: implement user authentication" \
  --output-format text \
  --model glm-5 \
  --dangerously-skip-permissions \
  > /app/memory/coding-task-$(date +%Y%m%d-%H%M%S).log 2>&1 &

# Capture the PID for tracking
echo $! > /app/memory/coding-task.pid
```

### Checking Progress

```bash
# Check if process is still running
ps aux | grep -E "claude.*coding-task" || echo "No active coding task"

# View latest log
ls -t /app/memory/coding-task-*.log | head -1 | xargs tail -50
```

## Issue-to-PR Workflow

### Step 1: Fetch Issue Details

```bash
# Using GitHub CLI (gh must be authenticated)
gh issue view <issue_number> --json title,body,labels,repository

# Or via API if gh not available
curl -s -H "Authorization: token $GITHUB_TOKEN" \
  "https://api.github.com/repos/owner/repo/issues/<issue_number>"
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

**Why this matters:**
- Previous branches may leave untracked files
- Local main can diverge from origin/main
- Stale branches accumulate and cause confusion
- Clean slate prevents "works on my machine" issues

### Step 3: Delegate to Claude Code

Use Claude Code print mode with a structured prompt:

```bash
export ANTHROPIC_BASE_URL="http://0.0.0.0:4000"
export ANTHROPIC_AUTH_TOKEN="sk-1234567890"

claude -p "
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

Work autonomously. Use the tools available (Read, Write, Edit, Bash for tests).
" --output-format text --model glm-5 --dangerously-skip-permissions 2>&1 | tee /app/memory/issue-<number>-work.log
```

### Step 4: Review Changes

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

## Timing Considerations

### Default Timeout

Claude Code tasks can run long. Default timeout for `docker_bash_execute` is 60 seconds.
For coding tasks, specify a longer timeout:

```bash
# Via docker_bash_execute tool
docker_bash_execute(
    command="export ANTHROPIC_BASE_URL='http://0.0.0.0:4000' && export ANTHROPIC_AUTH_TOKEN='sk-1234567890' && claude -p '...' --model glm-5 --dangerously-skip-permissions",
    timeout_seconds=1800  # 30 minutes
)
```

### Recommended Timeouts by Task Type

| Task Type | Recommended Timeout |
|-----------|-------------------|
| Quick fix (typo, small bug) | 5 minutes (300s) |
| Feature implementation | 15-30 minutes (900-1800s) |
| Complex refactor | 30-60 minutes (1800-3600s) |

### Maximum Limits

- `docker_bash_execute` max: 300 seconds (5 minutes)
- For longer tasks, use `nohup` + background execution
- Check progress periodically via log files

## Error Handling

### Claude Code Fails

```bash
# Check the log for errors
tail -100 /app/memory/issue-<number>-work.log

# Common issues:
# - File not found: repo not cloned correctly
# - Permission denied: check git credentials
# - Timeout: task too complex, split into smaller pieces
```

### Tests Fail

```bash
# Run tests manually to see full output
npm test  # or pytest, cargo test, etc.

# Fix interactively if needed
export ANTHROPIC_BASE_URL="http://0.0.0.0:4000"
export ANTHROPIC_AUTH_TOKEN="sk-1234567890"
claude -p "Tests are failing with: <error>. Fix the tests." --model glm-5 --dangerously-skip-permissions
```

### PR Creation Fails

```bash
# Check gh authentication
gh auth status

# Check branch exists remotely
git branch -r | grep issue-

# Manual PR creation
gh pr create --web  # opens browser (if headed mode)
```

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

## Best Practices

1. **Start from clean main** - Always `git reset --hard origin/main` and `git clean -fd` before creating a branch
2. **Clean up stale branches** - Remove merged branches to keep the workspace tidy
3. **Create descriptive branch names**: `issue-123-add-user-auth`
4. **Keep commits atomic** and well-scoped
5. **Run tests** before pushing
6. **Don't force push** - if something goes wrong, create a new branch
7. **Log everything** - save output to files for debugging
8. **Set expectations** - tell the user what you'll do before starting

## Restrictions

- **Never push directly to main** - always use feature branches
- **Never force push** to shared branches
- **Don't merge your own PRs** - user reviews them
- **Don't delete branches** until PR is merged
- **Don't commit secrets** - check for .env files, tokens, etc.

## Example Interactions

**User**: "Work on issue #42"

**Your response**:
1. Fetch issue #42 details
2. Clone/navigate to the repo
3. Reset to clean main: `git reset --hard origin/main && git clean -fd`
4. Clean up stale branches: `git branch --merged main | grep -v main | xargs -r git branch -d`
5. Create fresh branch `issue-42-<short-desc>`
6. Run Claude Code in print mode to implement the fix
7. Review the changes
8. Push and create PR
9. Send summary: "Issue #42 complete! PR created: <url>"

**User**: "Fix the bug in the auth module"

**Your response**:
1. Navigate to the relevant repo
2. Reset to clean main: `git reset --hard origin/main && git clean -fd`
3. Create fresh branch `fix-auth-bug`
4. Use Claude Code to understand and fix the bug
5. Run tests to verify
6. Commit and push
7. Send summary of what was fixed
