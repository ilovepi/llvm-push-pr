# LLVM PR Automation Tool

A Python script to simplify the process of creating pull requests for LLVM, especially when dealing with a stack of commits. This tool automates branch creation, pushing, and opening pull requests on GitHub.

## Features

* **Portability**: Written in Python, it works on macOS, Linux, and Windows (with Git and Python installed).
* **Stacked Commits**: Pushes a series of commits as individual pull requests, as per the LLVM workflow.
* **Automatic Branching**: Generates temporary, descriptive branch names so you don't have to.
* **GitHub CLI Integration**: Uses the `gh` command-line tool to create pull requests.

## Prerequisites

1.  **Python 3.6+**: Ensure you have Python installed.
2.  **Git**: Git must be installed and available in your system's PATH.
3.  **GitHub CLI (`gh`)**: This tool is required for creating pull requests. You can find installation instructions at [cli.github.com](https://cli.github.com/).
    * After installing, make sure to authenticate with `gh auth login`.
4.  **Configured Git Remotes**: For the best experience, especially when contributing to LLVM, it's recommended to have two remotes configured:
    * `origin`: Your fork of the `llvm-project` repository (e.g., `git@github.com:<your-username>/llvm-project.git`).
    * `upstream`: The main LLVM repository (e.g., `https://github.com/llvm/llvm-project.git`).

    This setup allows the script to create branches based on the official `upstream` repository while pushing them to your `origin` fork, which is the standard workflow for creating pull requests.

## Setup

1.  **Clone the repository or save the files**:
    Place `llvm_pr.py`, `README.md`, and `requirements.txt` in a directory.

2.  **Install Dependencies**:
    It's recommended to use a virtual environment.

    ```bash
    python3 -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
    pip install -r requirements.txt
    ```
    *(Note: This script currently has no external Python dependencies, but `requirements.txt` is included for good practice).*

3.  **Make the script executable (Optional, on macOS/Linux)**:
    ```bash
    chmod +x llvm_pr.py
    ```

## Usage

### Pushing a Single Commit

If you have one commit on your current branch that you want to turn into a PR:

1.  Ensure your commit is clean and has a descriptive message (this will be the PR title and body).
2.  Run the script:
    ```bash
    python llvm_pr.py
    ```
    Or if executable:
    ```bash
    ./llvm_pr.py
    ```

### Pushing a Stack of Commits

If you have multiple commits stacked on top of the base branch (`main` by default):

1.  Make sure your commits are ordered correctly. You can use `git rebase -i` to reorder or squash them.
2.  Run the script:
    ```bash
    python llvm_pr.py
    ```
    The script will process each commit from the oldest to the newest, creating a separate PR for each.

### Command-line Options

* `--base <branch>`: Specify a different base branch. Default is `main`.
    ```bash
    python llvm_pr.py --base release/15.x
    ```
* `--remote <name>`: Specify the remote for your fork to push to. Default is `origin`.
* `--upstream-remote <name>`: Specify the remote that points to the upstream repository. Default is `upstream`.
* `--prefix <prefix>`: Specify a different prefix for temporary branches. Default is `dev/`.
* `-f` or `--force`: Force push the generated branches. Useful if you've updated a commit and need to update the corresponding branch. **Use with caution.**
* `--draft`: Create all pull requests as drafts.
* `--auto-merge`: Enable auto-merge for the pull requests.
* `--merge`: Merge the pull requests immediately after creation.
* `--no-pr`: Pushes the branches to your remote but stops before creating pull requests. This is useful if you want to inspect the branches on GitHub first.
* `[commits...]`: You can provide one or more specific commit hashes to process, instead of all commits on the current branch.
    ```bash
    python llvm_pr.py <commit-hash-1> <commit-hash-2>
    ```

### Workflow Example

1.  Create a new feature branch from the `main` branch:
    ```bash
    git checkout -b my-awesome-feature
    ```
2.  Make your changes and create a few commits:
    ```bash
    git add file1.cpp
    git commit -m "feat: Add initial implementation"
    git add file2.cpp
    git commit -m "refactor: Improve performance of algorithm"
    ```
3.  Run the script to push both commits as separate PRs:
    ```bash
    python llvm_pr.py
    ```
4.  The script will:
    * Create a branch like `dev/feat-add-initial-implementation-abcdef1` and push it.
    * Open a PR for that branch.
    * Create a branch like `dev/refactor-improve-performance-of-algorithm-1234567` and push it.
    * Open a second PR for the second branch.
    * Clean up the temporary local branches and return you to `my-awesome-feature`.

## How It Works

For each commit in the stack, the script performs these steps:

1.  Reads the commit's title and body.
2.  Generates a unique, descriptive branch name based on the commit message.
3.  Creates this new branch from the specified `--base` branch.
4.  Cherry-picks the commit onto the new branch.
5.  Pushes the new branch to your remote repository.
6.  Uses the `gh` CLI to open a pull request with the commit's title and body. The script passes the commit body to `gh` via standard input to ensure that formatting (including line breaks) is preserved.
7.  After processing all commits, it cleans up all temporary local branches.
