#!/bin/sh
set -eu

log() {
    printf '%s\n' "$*"
}

configure_git() {
    git config --global user.name "${GARBANZO_GIT_USER_NAME:-QueryPlanner}"
    git config --global user.email "${GARBANZO_GIT_USER_EMAIL:-chiragnpatil@gmail.com}"
    git config --global init.defaultBranch "${GARBANZO_GIT_DEFAULT_BRANCH:-main}"
    git config --global fetch.prune true
    git config --global push.autoSetupRemote true
}

resolve_github_token() {
    if [ -n "${GH_TOKEN:-}" ]; then
        printf '%s' "$GH_TOKEN"
        return 0
    fi

    if [ -n "${GITHUB_TOKEN:-}" ]; then
        printf '%s' "$GITHUB_TOKEN"
        return 0
    fi

    return 1
}

setup_gh_auth() {
    if ! token="$(resolve_github_token)"; then
        log "Garbanzo bootstrap: skipping GitHub auth because GH_TOKEN is missing."
        return 0
    fi

    export GH_TOKEN="$token"

    if gh auth status >/dev/null 2>&1; then
        log "Garbanzo bootstrap: GitHub CLI is ready."
    else
        log "Garbanzo bootstrap: validating GitHub CLI token from environment."
        if ! gh auth status; then
            log "Garbanzo bootstrap: GitHub CLI could not validate GH_TOKEN."
            return 0
        fi
    fi

    if gh auth setup-git >/dev/null 2>&1; then
        log "Garbanzo bootstrap: Git credential helper configured."
        return 0
    fi

    log "Garbanzo bootstrap: unable to configure git credential helper via gh."
}

clone_bootstrap_repo_if_needed() {
    repo_slug="${GARBANZO_BOOTSTRAP_REPO:-}"
    if [ -z "$repo_slug" ]; then
        return 0
    fi

    workspace_root="${GARBANZO_WORKSPACE_ROOT:-$GARBANZO_HOME/workspace}"
    repo_name="$(basename "$repo_slug")"
    repo_dir="${GARBANZO_BOOTSTRAP_REPO_DIR:-$workspace_root/$repo_name}"
    repo_https_url="https://github.com/$repo_slug.git"

    mkdir -p "$workspace_root"

    if [ -d "$repo_dir/.git" ]; then
        git -C "$repo_dir" remote set-url origin "$repo_https_url"
        log "Garbanzo bootstrap: workspace repo already exists at $repo_dir."
        return 0
    fi

    if ! resolve_github_token >/dev/null 2>&1; then
        log "Garbanzo bootstrap: skipping repo clone because GH_TOKEN is missing."
        return 0
    fi

    log "Garbanzo bootstrap: cloning $repo_slug into $repo_dir."
    if gh repo clone "$repo_slug" "$repo_dir"; then
        git -C "$repo_dir" remote set-url origin "$repo_https_url"
        return 0
    fi

    log "Garbanzo bootstrap: gh repo clone failed; leaving workspace unchanged."
}

main() {
    if [ -z "${GARBANZO_HOME:-}" ]; then
        log "Garbanzo bootstrap: GARBANZO_HOME is not set, skipping."
        return 0
    fi

    mkdir -p "$GARBANZO_HOME/workspace"
    configure_git
    setup_gh_auth
    clone_bootstrap_repo_if_needed
}

main "$@"
