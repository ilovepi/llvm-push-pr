#!/usr/bin/env python3

import argparse
import re
import subprocess
import sys
import time
from typing import List, Optional


class Printer:
    def __init__(self, dry_run: bool = False, verbose: bool = False, quiet: bool = False):
        self.dry_run = dry_run
        self.verbose = verbose
        self.quiet = quiet

    def print(self, message: str, file=sys.stdout):
        if self.quiet and file == sys.stdout:
            return
        print(message, file=file)

    def run_command(
        self,
        command: List[str],
        check: bool = True,
        capture_output: bool = False,
        text: bool = False,
        input: Optional[str] = None,
        read_only: bool = False,
    ) -> subprocess.CompletedProcess:
        if self.dry_run and not read_only:
            self.print(f"[Dry Run] Would run: {' '.join(command)}")
            return subprocess.CompletedProcess(command, 0, "", "")

        if self.verbose:
            self.print(f"Running: {' '.join(command)}")

        try:
            return subprocess.run(
                command,
                check=check,
                capture_output=capture_output,
                text=text,
                input=input,
            )
        except FileNotFoundError:
            self.print(
                f"Error: Command '{command[0]}' not found. Is it installed and in your PATH?",
                file=sys.stderr,
            )
            sys.exit(1)
        except subprocess.CalledProcessError as e:
            if check:
                self.print(f"Error running command: {' '.join(command)}", file=sys.stderr)
                if e.stdout:
                    self.print(f"--- stdout ---\n{e.stdout}", file=sys.stderr)
                if e.stderr:
                    self.print(f"--- stderr ---\n{e.stderr}", file=sys.stderr)
                sys.exit(1)
            return e


class LLVMPRAutomator:
    def __init__(self, args: argparse.Namespace, printer: Printer):
        self.args = args
        self.printer = printer
        self.original_branch: str = ""
        self.repo_slug: str = ""
        self.created_branches: List[str] = []

    def _run_cmd(self, command: List[str], read_only: bool = False, **kwargs):
        """Wrapper for run_command that passes the dry_run flag."""
        return self.printer.run_command(command, read_only=read_only, **kwargs)

    def _get_repo_slug(self) -> str:
        """Gets the GitHub repository slug from the remote URL."""
        result = self._run_cmd(
            ["git", "remote", "get-url", self.args.remote],
            capture_output=True,
            text=True,
            read_only=True,
        )
        url = result.stdout.strip()
        match = re.search(r"github\.com[/:]([\w.-]+/[\w.-]+)", url)
        if not match:
            self.printer.print(
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

    def _rebase_current_branch(self):
        """Rebases the current branch on top of the upstream base."""
        target = f"{self.args.upstream_remote}/{self.args.base}"
        self.printer.print(
            f"\nFetching from '{self.args.upstream_remote}' and rebasing '{self.original_branch}' on top of '{target}'..."
        )
        self._run_cmd(["git", "fetch", self.args.upstream_remote, self.args.base])
        self._run_cmd(["git", "rebase", target])

    def _get_commit_stack(self) -> List[str]:
        """Gets the stack of commits between the current branch's HEAD and its merge base with upstream."""
        target = f"{self.args.upstream_remote}/{self.args.base}"
        merge_base_result = self._run_cmd(
            ["git", "merge-base", "HEAD", target],
            capture_output=True,
            text=True,
            read_only=True,
        )
        merge_base = merge_base_result.stdout.strip()
        if not merge_base:
            self.printer.print(
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
        return [c for c in commits if c]

    def _get_commit_details(self, commit_hash: str) -> tuple[str, str]:
        """Gets the title and body of a commit."""
        result = self._run_cmd(
            ["git", "show", "-s", "--format=%s%n%n%b", commit_hash],
            capture_output=True,
            text=True,
            read_only=True,
        )
        parts = result.stdout.strip().split("\n\n", 1)
        title = parts[0]
        body = parts[1] if len(parts) > 1 else ""
        return title, body

    def _sanitize_for_branch_name(self, text: str) -> str:
        """Sanitizes a string to be used as a git branch name."""
        sanitized = re.sub(r"[^\w\s-]", "", text).strip().lower()
        return re.sub(r"[-\s]+", "-", sanitized)

    def _create_and_push_branch_for_commit(
        self, commit_hash: str, base_branch_name: str, index: int
    ) -> str:
        """Creates and pushes a temporary branch pointing to a specific commit."""
        branch_name = f"{self.args.prefix}{base_branch_name}-{index + 1}"
        commit_title, _ = self._get_commit_details(commit_hash)
        self.printer.print(f"\nProcessing commit {commit_hash[:7]}: {commit_title}")
        self.printer.print(f"Creating and pushing temporary branch '{branch_name}'")

        self._run_cmd(["git", "branch", "-f", branch_name, commit_hash])
        push_command = ["git", "push", self.args.remote, branch_name]
        self._run_cmd(push_command)
        self.created_branches.append(branch_name)
        return branch_name

    def _create_pr(self, head_branch: str) -> Optional[str]:
        """Creates a GitHub Pull Request."""
        self.printer.print(f"Creating pull request for '{head_branch}'...")
        pr_command = [
            "gh",
            "pr",
            "create",
            "--repo",
            self.repo_slug,
            "--base",
            self.args.base,
            "--head",
            head_branch,
            "--fill",
        ]
        if self.args.draft:
            pr_command.append("--draft")
        result = self._run_cmd(pr_command, text=True, capture_output=True)
        pr_url = result.stdout.strip()
        if not self.args.dry_run:
            self.printer.print(f"Pull request created: {pr_url}")
        return pr_url

    def _merge_pr(self, pr_url: str):
        """Merges a PR, retrying if it's not yet mergeable."""
        if not pr_url:
            return

        if self.args.dry_run:
            self.printer.print(f"[Dry Run] Would merge {pr_url}")
            return

        max_retries = 10
        retry_delay = 5  # seconds
        for i in range(max_retries):
            self.printer.print(f"Attempting to merge {pr_url} (attempt {i+1}/{max_retries})...")
            merge_cmd = ["gh", "pr", "merge", pr_url, "--squash", "--delete-branch"]
            if self.args.auto_merge:
                merge_cmd.insert(3, "--auto")

            result = self._run_cmd(
                merge_cmd, check=False, capture_output=True, text=True
            )

            if result.returncode == 0:
                self.printer.print("Successfully merged.")
                time.sleep(2)  # Give GitHub a moment to reflect the merge
                return

            stderr = result.stderr.lower()
            if "pull request is not mergeable" in stderr:
                self.printer.print(f"PR not mergeable yet. Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                self.printer.print(
                    f"Error: Failed to merge PR for a critical reason.", file=sys.stderr
                )
                self.printer.print(f"--- stderr ---\n{result.stderr}", file=sys.stderr)
                sys.exit(1)

        self.printer.print(
            f"Error: PR was not mergeable after {max_retries} attempts.",
            file=sys.stderr,
        )
        sys.exit(1)

    def run(self):
        self.repo_slug = self._get_repo_slug()
        self.original_branch = self._get_current_branch()
        self.printer.print(f"On branch: {self.original_branch}")

        try:
            self._rebase_current_branch()
            initial_commits = self._get_commit_stack()

            if not initial_commits:
                self.printer.print("No new commits to process.")
                return

            if self.args.auto_merge and len(initial_commits) > 1:
                self.printer.print(
                    "Error: --auto-merge is only supported for a single commit.",
                    file=sys.stderr,
                )
                sys.exit(1)

            if self.args.no_merge and len(initial_commits) > 1:
                self.printer.print(
                    "Error: --no-merge is only supported for a single commit. "
                    "For stacks, the script must merge sequentially.",
                    file=sys.stderr,
                )
                sys.exit(1)

            self.printer.print(f"\nFound {len(initial_commits)} commit(s) to process.")
            branch_base_name = self.original_branch
            if self.original_branch in ["main", "master"]:
                first_commit_title, _ = self._get_commit_details(initial_commits[0])
                branch_base_name = self._sanitize_for_branch_name(first_commit_title)

            for i in range(len(initial_commits)):
                if i > 0:
                    self._rebase_current_branch()

                commits = self._get_commit_stack()
                if not commits:
                    self.printer.print("\nSuccess! All commits have been landed.")
                    break

                commit_to_process = commits[0]

                temp_branch = self._create_and_push_branch_for_commit(
                    commit_to_process, branch_base_name, i
                )
                pr_url = self._create_pr(temp_branch)

                if not self.args.no_merge:
                    self._merge_pr(pr_url)

        finally:
            self._cleanup()

    def _cleanup(self):
        """Cleans up by returning to the original branch and deleting all temporary branches."""
        self.printer.print(f"\nReturning to original branch: {self.original_branch}")
        self._run_cmd(["git", "checkout", self.original_branch], capture_output=True)
        if self.created_branches:
            self.printer.print("Cleaning up temporary local branches...")
            self._run_cmd(["git", "branch", "-D"] + self.created_branches)
            self.printer.print("Cleaning up temporary remote branches...")
            for branch in self.created_branches:
                self._run_cmd(
                    ["git", "push", self.args.remote, "--delete", branch], check=False
                )


def check_prerequisites(printer: Printer):
    """Checks if git and gh are installed and if inside a git repository."""
    printer.print("Checking prerequisites...")
    printer.run_command(["git", "--version"], capture_output=True, read_only=True)
    printer.run_command(["gh", "--version"], capture_output=True, read_only=True)
    result = printer.run_command(
        ["git", "rev-parse", "--is-inside-work-tree"],
        check=False,
        capture_output=True,
        text=True,
        read_only=True,
    )
    if result.returncode != 0 or result.stdout.strip() != "true":
        printer.print(
            "Error: This script must be run inside a git repository.", file=sys.stderr
        )
        sys.exit(1)
    printer.print("Prerequisites met.")


def main():
    parser = argparse.ArgumentParser(
        description="Create and land a stack of Pull Requests."
    )
    GITHUB_REMOTE_NAME = "origin"
    UPSTREAM_REMOTE_NAME = "upstream"
    BASE_BRANCH = "main"
    BRANCH_PREFIX = "dev/"

    parser.add_argument(
        "--base",
        default=BASE_BRANCH,
        help=f"Base branch to target (default: {BASE_BRANCH})",
    )
    parser.add_argument(
        "--remote",
        default=GITHUB_REMOTE_NAME,
        help=f"Remote for your fork to push to (default: {GITHUB_REMOTE_NAME})",
    )
    parser.add_argument(
        "--upstream-remote",
        default=UPSTREAM_REMOTE_NAME,
        help=f"Remote for the upstream repository (default: {UPSTREAM_REMOTE_NAME})",
    )
    parser.add_argument(
        "--prefix",
        default=BRANCH_PREFIX,
        help=f"Prefix for temporary branches (default: {BRANCH_PREFIX})",
    )
    parser.add_argument(
        "--draft", action="store_true", help="Create pull requests as drafts."
    )
    parser.add_argument(
        "--no-merge", action="store_true", help="Create PRs but do not merge them."
    )
    parser.add_argument(
        "--auto-merge",
        action="store_true",
        help="Enable auto-merge for each PR instead of attempting to merge immediately.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print commands without executing them."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-v", "--verbose", action="store_true", help="Print all commands being run."
    )
    group.add_argument(
        "-q", "--quiet", action="store_true", help="Print only essential output and errors."
    )

    args = parser.parse_args()
    if args.prefix and not args.prefix.endswith("/"):
        args.prefix += "/"

    printer = Printer(dry_run=args.dry_run, verbose=args.verbose, quiet=args.quiet)
    check_prerequisites(printer)
    automator = LLVMPRAutomator(args, printer)
    automator.run()


if __name__ == "__main__":
    main()