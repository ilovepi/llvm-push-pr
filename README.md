# LLVM PR Automation Tool

A Python script to reliably land a stack of commits as sequential pull requests, designed specifically for repositories like LLVM with a squash-and-merge policy. This tool serves as a robust replacement for `git push` when a project requires all changes to go through PRs.

## Features

*   **Portability**: Written in Python, works on macOS, Linux, and Windows.
*   **Sequential Landing**: Correctly lands a series of dependent commits by repeatedly rebasing and merging pull requests one by one.
*   **Preserves Commit Messages**: Uses the GitHub API to ensure the exact original commit message is used when the PR is squashed, preventing mangled commit history.
*   **Automatic Branching**: Generates predictable, counter-based temporary branch names.
*   **Robust Merging**: By default, it waits for each PR to be mergeable (polling for CI checks to pass) before merging.

## Prerequisites

1.  **Python 3.6+**
2.  **Git**
3.  **GitHub CLI (`gh`)**: Version 2.5.0 or newer is required for API commands.
    *   Authenticate with `gh auth login`. Ensure your token has the `repo` scope.
4.  **Configured Git Remotes**:
    *   `origin`: Your fork (e.g., `git@github.com:<your-username>/llvm-project.git`).
    *   `upstream`: The main repository (e.g., `https://github.com/llvm/llvm-project.git`).

## Setup

1.  Place the `llvm-push-pr.py` script in a directory in your `PATH`.
2.  Make it executable: `chmod +x llvm-push-pr.py`

## Usage

The script's default behavior is to land your entire local commit stack onto the `main` branch.

1.  Create a feature branch with your stack of commits.
2.  Run the script:
    ```bash
    llvm-push-pr.py
    ```
    The script will then take over, performing the entire sequential landing process.

### Command-line Options

*   `--base <branch>`: The base branch to target (default: `main`).
*   `--remote <name>`: Your fork's remote name (default: `origin`).
*   `--upstream-remote <name>`: The upstream remote name (default: `upstream`).
*   `--prefix <prefix>`: Prefix for temporary branches (default: `dev/`).
*   `--no-merge`: Create all PRs but do not merge them. This is useful if you want to inspect the PRs on GitHub before they are landed.
*   `--auto-merge`: Enable auto-merge for each PR instead of waiting to merge sequentially.
*   `-f`, `--force`: Force push temporary branches.
*   `--draft`: Create PRs as drafts.
*   `--dry-run`: Print commands without executing them.

## How It Works

The script operates as a state machine, repeating a cycle until your local branch has no more commits to land. This is the only way to reliably land a stack in a squash-and-merge repository while preserving commit history.

**The Loop:**

1.  **Rebase**: The script begins by rebasing your current branch onto the latest `upstream/main`. This ensures the first commit to be processed is clean.
2.  **Get Top Commit**: It identifies the oldest commit on your branch that is not yet on `main`.
3.  **Create Branch & PR**: It creates a temporary branch pointing to that single commit, pushes it, and opens a pull request.
4.  **Wait & Merge**:
    *   If `--no-merge` is **not** used, the script polls the GitHub API, waiting for the PR to become mergeable (e.g., for CI to pass).
    *   Once mergeable, it uses a direct API call to merge the PR, providing the **exact original commit title and body**. This is the key to avoiding corrupted commit messages.
5.  **Repeat**: The script automatically deletes the temporary remote branch and then **starts the loop over**. It goes back to step 1, rebasing your local branch (which now has one less commit) on top of the newly-updated `main`. This process continues until the branch is fully merged.
