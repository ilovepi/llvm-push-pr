# LLVM PR Automation Tool

A Python script to simplify the process of creating pull requests for LLVM, especially when dealing with a stack of (potentially dependent) commits. This tool automates branch creation, pushing, and opening pull requests on GitHub.

## Features

*   **Portability**: Written in Python, it works on macOS, Linux, and Windows.
*   **Stacked Commits**: Correctly handles a series of dependent commits, creating a chain of pull requests.
*   **Automatic Branching**: Generates temporary, descriptive branch names.
*   **GitHub CLI Integration**: Uses the `gh` command-line tool to create pull requests, using the idiomatic `--fill` flag.
*   **Atomic Merging**: When used with `--merge` or `--auto-merge`, it merges the entire stack of PRs in a single operation.

## Prerequisites

1.  **Python 3.6+**: Ensure you have Python installed.
2.  **Git**: Git must be installed and available in your system's PATH.
3.  **GitHub CLI (`gh`)**: This tool is required. Find installation instructions at [cli.github.com](https://cli.github.com/).
    *   After installing, make sure to authenticate with `gh auth login`.
4.  **Configured Git Remotes**: For the best experience, it's recommended to have two remotes configured:
    *   `origin`: Your fork of the `llvm-project` repository (e.g., `git@github.com:<your-username>/llvm-project.git`).
    *   `upstream`: The main LLVM repository (e.g., `https://github.com/llvm/llvm-project.git`).

## Setup

1.  Place the `llvm-push-pr.py` script in a directory in your `PATH`.
2.  Make the script executable (on macOS/Linux):
    ```bash
    chmod +x llvm-push-pr.py
    ```

## Usage

### Pushing a Single Commit

1.  Ensure your commit has a descriptive message (this will become the PR title and body).
2.  Run the script:
    ```bash
    llvm-push-pr.py
    ```

### Pushing a Stack of Dependent Commits

1.  Make sure your commits are ordered correctly on your branch.
2.  Run the script:
    ```bash
    llvm-push-pr.py
    ```
    The script will create a chain of pull requests, where each PR targets the branch of the previous one.

### Workflow Example

1.  Create a new feature branch from the `main` branch:
    ```bash
    git checkout -b my-awesome-feature
    ```
2.  Make your changes and create a few dependent commits:
    ```bash
    git add helper.cpp
    git commit -m "feat: Add helper function"
    git add main.cpp
    git commit -m "feat: Use helper function in main"
    ```
3.  Run the script to push both commits as a stack of PRs:
    ```bash
    llvm-push-pr.py
    ```
4.  The script will:
    *   Create a branch like `dev/feat-add-helper-function-abcdef1` from `upstream/main`.
    *   Open **PR #1** for this branch, targeting `main`.
    *   Create a second branch `dev/feat-use-helper-function-1234567` from the first branch.
    *   Open **PR #2** for this second branch, targeting `dev/feat-add-helper-function-abcdef1`.
    *   Clean up the temporary local branches and return you to `my-awesome-feature`.

### Command-line Options

*   `--base <branch>`: The base branch in the upstream repository to target. Default is `main`.
*   `--remote <name>`: The remote for your fork to push to. Default is `origin`.
*   `--upstream-remote <name>`: The remote that points to the upstream repository. Default is `upstream`.
*   `--prefix <prefix>`: The prefix for temporary branches. Default is `dev/`.
*   `-f`, `--force`: Force push the generated branches.
*   `--draft`: Create all pull requests as drafts.
*   `--merge`: Merge the final pull request in the stack immediately after creation. This will merge the entire stack.
*   `--auto-merge`: Enable auto-merge on the final pull request in the stack.
*   `--no-pr`: Push branches but do not create pull requests.
*   `--dry-run`: Print the commands that would be executed without running them.
*   `[commits...]`: Specific commit hashes to process.

## How It Works

The script is designed to correctly handle stacks of dependent commits by creating a chain of pull requests. For a stack of commits A, B, and C, it performs these steps:

1.  **For the first commit (A):**
    *   Creates a branch `branch-A` from `upstream/main`.
    *   Cherry-picks commit A onto `branch-A`.
    *   Pushes `branch-A` to your `origin` remote.
    *   Creates **PR #1** targeting `main` (`branch-A` -> `main`).

2.  **For the second commit (B):**
    *   Creates a branch `branch-B` from `branch-A`.
    *   Cherry-picks commit B onto `branch-B`.
    *   Pushes `branch-B` to `origin`.
    *   Creates **PR #2** targeting `branch-A` (`branch-B` -> `branch-A`).

3.  **For the third commit (C):**
    *   Creates a branch `branch-C` from `branch-B`.
    *   Cherry-picks commit C onto `branch-C`.
    *   Pushes `branch-C` to `origin`.
    *   Creates **PR #3** targeting `branch-B` (`branch-C` -> `branch-B`).

When the final PR (#3) is merged (either manually or with `--merge`), GitHub automatically merges the entire chain (PRs #2 and #1) into `main`, ensuring the whole stack lands together correctly.