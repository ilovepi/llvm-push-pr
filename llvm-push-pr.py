#!/usr/bin/env python3

import argparse
import re
import subprocess
import sys
from typing import List, Optional, Tuple


def run_command(
    command: List[str],
    check: bool = True,
    capture_output: bool = False,
    text: bool = False,
    input: Optional[str] = None,
    dry_run: bool = False,
    read_only: bool = False,
) -> subprocess.CompletedProcess:
    """
    Runs a command. In dry_run mode, it prints the command instead of running it,
    unless read_only is True.
    """
    if dry_run and not read_only:
        print(f"[Dry Run] Would run: {' '.join(command)}")
        return subprocess.CompletedProcess(command, 0, "", "")

    try:
        return subprocess.run(
            command,
            check=check,
            capture_output=capture_output,
            text=text,
            input=input,
        )
    except FileNotFoundError:
        print(
            f"Error: Command '{command[0]}' not found. Is it installed and in your PATH?",
            file=sys.stderr,
        )
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {' '.join(command)}", file=sys.stderr)
        if e.stdout:
            print(f"--- stdout ---\n{e.stdout}", file=sys.stderr)
        if e.stderr:
            print(f"--- stderr ---\n{e.stderr}", file=sys.stderr)
        sys.exit(1)


class LLVMPRAutomator:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.original_branch: str = ""
        self.created_branches: List[str] = []
        self.repo_slug: str = ""

    def _run_cmd(self, command: List[str], read_only: bool = False, **kwargs):
        """Wrapper for run_command that passes the dry_run flag."""
        return run_command(
            command, dry_run=self.args.dry_run, read_only=read_only, **kwargs
        )

    def _get_repo_slug(self) -> str:
        """Gets the GitHub repository slug (e.g., 'owner/repo') from the remote URL."""
        result = self._run_cmd(
            ["git", "remote", "get-url", self.args.remote],
            capture_output=True,
            text=True,
            read_only=True,
        )
        url = result.stdout.strip()
        match = re.search(r"github\.com[/:]([\w-]+/[\w-]+)", url)
        if not match:
            print(
                f"Error: Could not parse repository slug from remote URL: {url}",
                file=sys.stderr,
            )
            sys.exit(1)
        return match.group(1).replace(".git", "")

    def _get_current_branch(self) -> str:
        """Gets the current git branch."""
        result = self._run_cmd(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            read_only=True,
        )
        return result.stdout.strip()

    def _get_commit_stack(self) -> List[str]:
        """Gets the stack of commits from HEAD to the base branch."""
        target = f"{self.args.upstream_remote}/{self.args.base}"
        print(f"Fetching from upstream remote '{self.args.upstream_remote}'...")
        self._run_cmd(["git", "fetch", self.args.upstream_remote, self.args.base])

        print(f"Finding merge base between HEAD and {target}...")
        merge_base_result = self._run_cmd(
            ["git", "merge-base", "HEAD", target],
            capture_output=True,
            text=True,
            read_only=True,
        )
        merge_base = merge_base_result.stdout.strip()

        if not merge_base:
            print(
                f"Error: Could not find a merge base between HEAD and {target}.",
                file=sys.stderr,
            )
            sys.exit(1)

        result = self._run_cmd(
            ["git", "rev-list", "--reverse", f"{merge_base}..HEAD"],
            capture_output=True,
            text=True,
            read_only=True,
        )
        commits = result.stdout.strip().split("\n")
        if not commits or commits == [""]:
            return []
        return commits

    def _get_commit_title(self, commit_hash: str) -> str:
        """Gets the title of a commit."""
        result = self._run_cmd(
            ["git", "show", "-s", "--format=%s", commit_hash],
            capture_output=True,
            text=True,
            read_only=True,
        )
        return result.stdout.strip()

    def _create_and_push_branch_for_commit(
        self, commit_hash: str, base_ref: str
    ) -> Optional[str]:
        """Creates a temporary branch for a commit and pushes it."""
        title = self._get_commit_title(commit_hash)

        sanitized_title = re.sub(r"[^\w\s-]", "", title).strip().lower()
        sanitized_title = re.sub(r"[-\s]+", "-", sanitized_title)
        branch_name = f"{self.args.prefix}{sanitized_title}-{commit_hash[:7]}"

        print(f"\nProcessing commit {commit_hash[:7]}: {title}")
        print(f"Creating temporary branch '{branch_name}' from '{base_ref}'")

        self._run_cmd(["git", "branch", "-f", branch_name, base_ref])

        print(f"Cherry-picking {commit_hash} onto {branch_name}")
        self._run_cmd(["git", "checkout", branch_name], capture_output=True)
        cherry_pick_result = self._run_cmd(
            ["git", "cherry-pick", commit_hash], check=False
        )

        if cherry_pick_result.returncode != 0:
            print(
                f"Error cherry-picking {commit_hash}. You may have a conflict.",
                file=sys.stderr,
            )
            print("Aborting cherry-pick...", file=sys.stderr)
            self._run_cmd(["git", "cherry-pick", "--abort"], check=False)
            return None

        push_command = ["git", "push", self.args.remote, branch_name]
        if self.args.force:
            push_command.append("--force")
        self._run_cmd(push_command)
        return branch_name

    def _create_pr(self, head_branch: str, base_branch: str) -> Optional[str]:
        """Creates a GitHub Pull Request using the gh CLI."""
        print(f"Creating pull request for '{head_branch}' targeting '{base_branch}'")
        pr_command = [
            "gh",
            "pr",
            "create",
            "--repo",
            self.repo_slug,
            "--base",
            base_branch,
            "--head",
            head_branch,
            "--fill",
        ]
        if self.args.draft:
            pr_command.append("--draft")

        result = self._run_cmd(pr_command, text=True, capture_output=True)
        pr_url = result.stdout.strip()
        if not self.args.dry_run:
            print(f"Pull request created: {pr_url}")
        return pr_url

    def _merge_pr(self, pr_url: str):
        """Merges or enables auto-merge for a pull request."""
        if self.args.auto_merge:
            print(f"Enabling auto-merge for {pr_url}")
            self._run_cmd(["gh", "pr", "merge", pr_url, "--auto", "--squash"])
        elif self.args.merge:
            print(f"Attempting to merge {pr_url} immediately.")
            self._run_cmd(["gh", "pr", "merge", pr_url, "--squash"])

    def _cleanup(self):
        """Cleans up by returning to the original branch and deleting temp branches."""
        if not self.original_branch:
            return
        print(f"\nSwitching back to original branch: {self.original_branch}")
        self._run_cmd(["git", "checkout", self.original_branch], capture_output=True)

        if self.created_branches:
            print("\nCleaning up temporary local branches:")
            for branch in self.created_branches:
                self._run_cmd(["git", "branch", "-D", branch])

    def run(self):
        self.repo_slug = self._get_repo_slug()
        self.original_branch = self._get_current_branch()
        print(f"On branch: {self.original_branch}")

        try:
            commits = self.args.commits or self._get_commit_stack()
            if not commits:
                print("No new commits to process.")
                return

            print(f"Found {len(commits)} commit(s) to process.")

            base_for_next_branch = f"{self.args.upstream_remote}/{self.args.base}"
            base_for_next_pr = self.args.base
            last_pr_url = None

            for commit in commits:
                temp_branch = self._create_and_push_branch_for_commit(
                    commit, base_for_next_branch
                )

                if temp_branch:
                    self.created_branches.append(temp_branch)
                    if not self.args.no_pr:
                        pr_url = self._create_pr(temp_branch, base_for_next_pr)
                        if pr_url:
                            last_pr_url = pr_url

                    # Prepare for the next iteration
                    base_for_next_branch = temp_branch
                    base_for_next_pr = temp_branch
                else:
                    print(
                        f"Stopping due to failed cherry-pick for commit {commit[:7]}",
                        file=sys.stderr,
                    )
                    sys.exit(1)

            if last_pr_url and (self.args.merge or self.args.auto_merge):
                self._merge_pr(last_pr_url)

        finally:
            self._cleanup()

        print("\nDone.")


def check_prerequisites(dry_run: bool = False):
    """Checks if git and gh are installed and if inside a git repository."""
    print("Checking prerequisites...")
    run_command(["git", "--version"], capture_output=True, read_only=True)
    run_command(["gh", "--version"], capture_output=True, read_only=True)
    result = run_command(
        ["git", "rev-parse", "--is-inside-work-tree"],
        check=False,
        capture_output=True,
        text=True,
        read_only=True,
    )
    if result.returncode != 0 or result.stdout.strip() != "true":
        print(
            "Error: This script must be run inside a git repository.", file=sys.stderr
        )
        sys.exit(1)
    print("Prerequisites met.")


def main():
    parser = argparse.ArgumentParser(
        description="Create LLVM Pull Requests from a stack of commits."
    )
    # Constants for default values
    GITHUB_REMOTE_NAME = "origin"
    UPSTREAM_REMOTE_NAME = "upstream"
    BASE_BRANCH = "main"
    BRANCH_PREFIX = "dev/"

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
        default=UPSTREAM_REMOTE_NAME,
        help=f"The remote that points to the upstream repository (default: {UPSTREAM_REMOTE_NAME}).",
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
        "--dry-run",
        action="store_true",
        help="Print the commands that would be executed without running them.",
    )
    parser.add_argument(
        "commits",
        nargs="*",
        help="Specific commit hashes to push. If empty, all commits since base branch are used.",
    )

    args = parser.parse_args()

    if args.auto_merge and args.merge:
        print(
            "Error: --auto-merge and --merge are mutually exclusive.", file=sys.stderr
        )
        sys.exit(1)

    check_prerequisites(args.dry_run)
    automator = LLVMPRAutomator(args)
    automator.run()


if __name__ == "__main__":
    main()
