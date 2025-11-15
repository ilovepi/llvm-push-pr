# How to Use the LLVM Pull Request Automator

This script is designed to automate the process of creating and landing a stack of pull requests from a local commit branch to the main branch of LLVM's GitHub repository.
While its possible to use this for normal workflows, it's main purpose is to give contributors a practical alternative to pushing directly to LLVM's main branch.
See the discussion at https://discourse.llvm.org/t/rfc-require-pull-requests-for-all-llvm-project-commits/88164 for more context.


## Prerequisites

Before running the script, ensure you have the following set up:

1.  **`git` command line tool:** The script relies on `git` for all local repository operations.
2.  **GitHub Token:** You must have a GitHub Personal Access Token with `repo` scope. This token must be set as an environment variable:
    ```bash
    export LLVM_GITHUB_TOKEN="your_github_token_here"
    ```
3.  **Git Remotes:** Your local repository must be configured with two remotes:
    *   `upstream`: The remote that points to the main LLVM repository (e.g., `https://github.com/llvm/llvm-project.git`).
    *   `origin`: The remote that points to your personal fork of the repository.

## Basic Usage

To run the script, navigate to your local `llvm-project` repository, check out the branch containing your stack of commits, and run:

```bash
python3 llvm_push_pr.py
```

This will:
1.  Fetch the latest changes from `upstream/main`.
2.  Rebase your current branch on top of `upstream/main`.
3.  For each commit in your branch (from oldest to newest):
    a.  Push the commit to a temporary branch on your fork (`origin`).
    b.  Create a pull request targeting the `upstream` repository's `main` branch.
    c.  Attempt to merge the pull request.
    d.  If the merge is successful, it will rebase the local branch again and proceed to the next commit.

If any rebase or merge fails, the script will abort and clean up after itself, leaving your repository in its original state.

## Examples

### Dry Run (Safe Mode)

To see what actions the script *would* perform without actually creating branches, pushing code, or opening pull requests, use the `--dry-run` flag. 

```bash
python3 llvm_push_pr.py --dry-run
```

### Creating Draft Pull Requests

If you want to create pull requests but not have them ready for review immediately, use the `--draft` flag.

```bash
python3 llvm_push_pr.py --draft
```

### Enabling Auto-Merge

You can use the `--auto-merge` flag to create a pull request and enable the "auto-merge" feature on GitHub, rather than having the script try to merge it directly.
This is only supported for a single-commit, as the script would need to block until your first PR landed to move onto the next, or otherwise be too complex for a simple script.

```bash
python3 llvm_push_pr.py --auto-merge
```

### Creating PRs Without Merging

If you only want to create the pull requests and then merge them manually later, use the `--no-merge` flag.
Currently, this is only supported for single-commit branches.

```bash
python3 llvm_push_pr.py --no-merge
```

## Command-Line Options

| Flag                | Description                                                                          | Default            |
| ------------------- | ------------------------------------------------------------------------------------ | ------------------ |
| `--base`            | The base branch to target with the pull requests.                                    | `main`             |
| `--remote`          | The remote for your personal fork to push temporary branches to.                     | `origin`           |
| `--upstream-remote` | The remote for the upstream repository to create pull requests against.              | `upstream`         |
| `--login`           | Your GitHub username. If not provided, it will be queried from the token.            | (auto-detected)    |
| `--prefix`          | The prefix for temporary branches created on your fork.                              | `users/<username>/`|
| `--draft`           | Create pull requests as drafts.                                                      | (not set)          |
| `--no-merge`        | Create pull requests but do not attempt to merge them. (Single commit only)          | (not set)          |
| `--auto-merge`      | Enable auto-merge on created pull requests instead of merging directly. (Single commit only) | (not set)      |
| `--dry-run`         | Print the commands that would be run without executing them.                         | (not set)          |
| `-v`, `--verbose`   | Print all commands being run and other verbose output.                               | (not set)          |
| `-q`, `--quiet`     | Print only essential output and errors, suppressing progress messages.               | (not set)          |
