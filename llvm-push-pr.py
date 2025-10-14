import subprocess
import argparse
import sys
import re
import os
from typing import List, Optional

# Configuration - could be moved to a config file
GITHUB_REMOTE_NAME = "origin"
BASE_BRANCH = "main"
BRANCH_PREFIX = "dev/"


def run_command(
    command: List[str],
    check: bool = True,
    capture_output: bool = False,
    text: bool = False,
    input: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """Runs a command and returns the result."""
    try:
        result = subprocess.run(
            command,
            check=check,
            capture_output=capture_output,
            text=text,
            input=input,
        )
        return result
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {' '.join(command)}", file=sys.stderr)
        print(f"Stderr: {e.stderr}", file=sys.stderr)
        print(f"Stdout: {e.stdout}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print(
            f"Error: Command '{command[0]}' not found. Is git installed and in your PATH?",
            file=sys.stderr,
        )
        sys.exit(1)


def get_current_branch() -> str:
    """Gets the current git branch."""
    result = run_command(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True
    )
    return result.stdout.strip()


def get_commit_stack(base_branch: str, upstream_remote: str) -> List[str]:
    """Gets the stack of commits from HEAD to the base branch."""
    target = f"{upstream_remote}/{base_branch}"
    print(f"Fetching from upstream remote '{upstream_remote}'...")
    run_command(["git", "fetch", upstream_remote, base_branch])

    # Find the merge base
    print(f"Finding merge base between HEAD and {target}...")
    merge_base_result = run_command(
        ["git", "merge-base", "HEAD", target], capture_output=True, text=True
    )
    merge_base = merge_base_result.stdout.strip()

    if not merge_base:
        print(
            f"Error: Could not find a merge base between HEAD and {target}.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Get commits from HEAD to the merge base
    result = run_command(
        ["git", "rev-list", "--reverse", f"{merge_base}..HEAD"],
        capture_output=True,
        text=True,
    )
    commits = result.stdout.strip().split("\n")
    if not commits or commits == [""]:
        print("No new commits to push.")
        sys.exit(0)
    return commits


def get_commit_details(commit_hash: str) -> (str, str):
    """Gets the title and body of a commit."""
    result = run_command(
        ["git", "show", "-s", "--format=%s%n%n%b", commit_hash],
        capture_output=True,
        text=True,
    )
    parts = result.stdout.strip().split("\n\n", 1)
    title = parts[0]
    body = parts[1] if len(parts) > 1 else ""
    return title, body


def create_and_push_branch_for_commit(
    commit_hash: str,
    base_branch: str,
    remote_name: str,
    upstream_remote: str,
    branch_prefix: str,
    force: bool,
):
    """Creates a temporary branch for a commit and pushes it."""
    title, _ = get_commit_details(commit_hash)

    # Sanitize title to create a branch name
    sanitized_title = re.sub(r"[^\w\s-]", "", title).strip().lower()
    sanitized_title = re.sub(r"[-\s]+", "-", sanitized_title)

    # Truncate to a reasonable length
    branch_name = f"{branch_prefix}{sanitized_title}-{commit_hash[:7]}"

    print(f"\nProcessing commit {commit_hash[:7]}: {title}")
    print(f"Creating temporary branch: {branch_name}")

    # Create the branch from the base branch ref
    base_ref = f"{upstream_remote}/{base_branch}"
    run_command(["git", "branch", "-f", branch_name, base_ref])

    # Cherry-pick the commit
    print(f"Cherry-picking {commit_hash} onto {branch_name}")
    run_command(["git", "checkout", branch_name], capture_output=True)
    cherry_pick_result = run_command(["git", "cherry-pick", commit_hash], check=False)

    if cherry_pick_result.returncode != 0:
        print(
            f"Error cherry-picking {commit_hash}. You may have a conflict.",
            file=sys.stderr,
        )
        print(
            "Aborting cherry-pick and switching back to original branch.",
            file=sys.stderr,
        )
        run_command(["git", "cherry-pick", "--abort"], check=False)
        return None, False

    # Push the branch
    push_command = ["git", "push", remote_name, branch_name]
    if force:
        push_command.append("--force")

    run_command(push_command)
    return branch_name, True


def create_pr(
    branch_name: str,
    title: str,
    body: str,
    base_branch: str,
    draft: bool,
    auto_merge: bool,
    merge: bool,
):
    """Creates a GitHub Pull Request using the gh CLI."""
    if not is_gh_installed():
        print(
            "'gh' CLI not found. Please install it to create pull requests.",
            file=sys.stderr,
        )
        print("See: https://cli.github.com/", file=sys.stderr)
        return

    print(f"Creating pull request for {branch_name}")
    pr_command = [
        "gh",
        "pr",
        "create",
        "--base",
        base_branch,
        "--head",
        branch_name,
        "--title",
        title,
    ]
    if draft:
        pr_command.append("--draft")

    # Pass the body via stdin to preserve formatting
    print("Passing PR body via stdin to preserve formatting.")
    result = run_command(pr_command, input=body, text=True, capture_output=True)
    pr_url = result.stdout.strip()
    print(f"Pull request created: {pr_url}")

    if auto_merge:
        print("Enabling auto-merge for the pull request.")
        run_command(["gh", "pr", "merge", pr_url, "--auto", "--squash"])
    elif merge:
        print("Attempting to merge the pull request immediately.")
        run_command(["gh", "pr", "merge", pr_url, "--squash"])


def is_gh_installed() -> bool:
    """Checks if the GitHub CLI 'gh' is installed."""
    try:
        run_command(["gh", "--version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def check_git_repository():
    """Checks if the current directory is a git repository."""
    result = run_command(
        ["git", "rev-parse", "--is-inside-work-tree"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or result.stdout.strip() != "true":
        print("Error: This script must be run inside a git repository.", file=sys.stderr)
        sys.exit(1)


def main():
    check_git_repository()
    parser = argparse.ArgumentParser(
        description="Create LLVM Pull Requests from a stack of commits."
    )
    parser.add_argument(
        "--base",
        default=BASE_BRANCH,
        help=f"The base branch to measure commits against (default: {BASE_BRANCH})",
    )
    parser.add_argument(
        "--remote",
        default=GITHUB_REMOTE_NAME,
        help=f"The remote for your fork to push to (default: {GITHUB_REMOTE_NAME})",
    )
    parser.add_argument(
        "--upstream-remote",
        default="upstream",
        help="The remote that points to the upstream repository (e.g., 'llvm/llvm-project').",
    )
    parser.add_argument(
        "--prefix",
        default=BRANCH_PREFIX,
        help=f"The prefix for temporary branches (default: {BRANCH_PREFIX})",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force push the branches. Use with caution.",
    )
    parser.add_argument(
        "--draft", action="store_true", help="Create pull requests as drafts."
    )
    parser.add_argument(
        "--no-pr",
        action="store_true",
        help="Push branches but do not create pull requests.",
    )
    parser.add_argument(
        "--auto-merge",
        action="store_true",
        help="Enable auto-merge for the pull requests.",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Merge the pull requests immediately after creation.",
    )
    parser.add_argument(
        "commits",
        nargs="*",
        help="Specific commit hashes to push. If empty, all commits since base branch are used.",
    )

    args = parser.parse_args()

    if args.auto_merge and args.merge:
        print("Error: --auto-merge and --merge are mutually exclusive.", file=sys.stderr)
        sys.exit(1)

    original_branch = get_current_branch()
    print(f"On branch: {original_branch}")

    if args.commits:
        commits = args.commits
    else:
        commits = get_commit_stack(args.base, args.upstream_remote)

    print(f"Found {len(commits)} commit(s) to process.")

    created_branches = []

    try:
        for commit in commits:
            title, body = get_commit_details(commit)

            temp_branch, success = create_and_push_branch_for_commit(
                commit,
                args.base,
                args.remote,
                args.upstream_remote,
                args.prefix,
                args.force,
            )

            if success and not args.no_pr:
                create_pr(
                    temp_branch,
                    title,
                    body,
                    args.base,
                    args.draft,
                    args.auto_merge,
                    args.merge,
                )
                created_branches.append(temp_branch)
            elif not success:
                print(
                    f"Skipping PR creation for failed commit {commit[:7]}",
                    file=sys.stderr,
                )
                # On failure, it is better to stop to let the user fix the issue.
                sys.exit(1)

    finally:
        print(f"\nSwitching back to original branch: {original_branch}")
        run_command(["git", "checkout", original_branch], capture_output=True)

        if created_branches:
            print("\nCleaning up temporary local branches:")
            for branch in created_branches:
                run_command(["git", "branch", "-D", branch])

    print("\nDone.")


if __name__ == "__main__":
    main()
