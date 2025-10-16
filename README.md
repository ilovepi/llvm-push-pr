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
*   `--no-merge`: Create a PR but do not merge it. Only supported for a single commit.
*   `--auto-merge`: Enable auto-merge for a PR. Only supported for a single commit.
*   `--draft`: Create PRs as drafts.
*   `--dry-run`: Print commands without executing them.
*   `-v`, `--verbose`: Print all commands being run.
*   `-q`, `--quiet`: Print only essential output and errors.
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Print all commands being run."
    )

    args = parser.parse_args()
    if args.prefix and not args.prefix.endswith("/"):

## How It Works

The script operates as a state machine, repeating a cycle until your local branch has no more commits to land.

**The Loop:**

1.  **Rebase**: The script begins by rebasing your current branch onto the latest `upstream/main`.
2.  **Get Top Commit**: It identifies the oldest commit on your branch that is not yet on `main`.
3.  **Create Branch & PR**: It creates a temporary branch pointing to that single commit, pushes it, and opens a pull request.
4.  **Wait & Merge**:
    *   Unless `--no-merge` is specified, the script polls the GitHub API, waiting for the PR to become mergeable.
    *   Once mergeable, it uses a direct API call to merge the PR, providing the **exact original commit title and body**.
5.  **Repeat**: The script then **starts the loop over**. It goes back to step 1, rebasing your local branch on top of the newly-updated `main`. This process continues until the branch is fully merged.