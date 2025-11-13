#!/usr/bin/env python3
"""A script to automate the creation and landing of a stack of Pull Requests."""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import List, Optional
from http.client import HTTPResponse


# TODO(user): When submitting upstream, change this to "llvm/llvm-project".
REPO_SLUG = "ilovepi/llvm-push-pr"

LLVM_GITHUB_TOKEN_VAR = "LLVM_GITHUB_TOKEN"


class CommandRunner:
    """Handles command execution and output.
    Supports dry runs and verbosity level."""

    def __init__(
        self, dry_run: bool = False, verbose: bool = False, quiet: bool = False
    ):
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
        stdin_input: Optional[str] = None,
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
                input=stdin_input,
            )
        except FileNotFoundError:
            sys.exit(
                f"Error: Command '{command[0]}' not found. Is it installed and in your PATH?"
            )
        except subprocess.CalledProcessError as e:
            self.print(f"Error running command: {' '.join(command)}", file=sys.stderr)
            if e.stdout:
                self.print(f"--- stdout ---\n{e.stdout}", file=sys.stderr)
            if e.stderr:
                self.print(f"--- stderr ---\n{e.stderr}", file=sys.stderr)
            raise e


class GitHubAPI:
    """A wrapper for the GitHub API."""

    BASE_URL = "https://api.github.com"

    def __init__(self, runner: CommandRunner, token: str):
        self.runner = runner
        self.headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "llvm-push-pr",
        }
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPHandler(), urllib.request.HTTPSHandler()
        )

    def _request(
        self, method: str, endpoint: str, json_payload: Optional[dict] = None
    ) -> HTTPResponse:
        url = f"{self.BASE_URL}{endpoint}"
        if self.runner.verbose:
            self.runner.print(f"API Request: {method.upper()} {url}")
            if json_payload:
                self.runner.print(f"Payload: {json_payload}")

        data = None
        headers = self.headers.copy()
        if json_payload:
            data = json.dumps(json_payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(
            url, data=data, headers=headers, method=method.upper()
        )

        try:
            return self.opener.open(req, timeout=30)
        except urllib.error.HTTPError as e:
            self.runner.print(
                f"Error making API request to {url}: {e}", file=sys.stderr
            )
            if self.runner.verbose:
                error_body = e.read().decode()
                if error_body:
                    self.runner.print(
                        f"Error response body: {error_body}", file=sys.stderr
                    )
            raise

    def _request_and_parse_json(
        self, method: str, endpoint: str, json_payload: Optional[dict] = None
    ) -> dict:
        with self._request(method, endpoint, json_payload) as response:
            # expect a 200 'OK' or 201 'Created' status on success and JSON body.
            if response.status not in [200, 201]:
                self.runner.print(
                    f"Warning: Expected status 200 or 201, but got {response.status}",
                    file=sys.stderr,
                )

            response_text = response.read().decode("utf-8")
            if response_text:
                return json.loads(response_text)
            return {}

    def _request_no_content(
        self, method: str, endpoint: str, json_payload: Optional[dict] = None
    ) -> None:
        with self._request(method, endpoint, json_payload) as response:
            # expected a 204 No Content status on success,
            # indicating the operation was successful but there is no body.
            if response.status != 204:
                self.runner.print(
                    f"Warning: Expected status 204, but got {response.status}",
                    file=sys.stderr,
                )

    def get_user_login(self) -> str:
        return self._request_and_parse_json("GET", "/user")["login"]

    def create_pr(
        self,
        head_branch: str,
        base_branch: str,
        title: str,
        body: str,
        draft: bool,
    ) -> Optional[str]:
        self.runner.print(f"Creating pull request for '{head_branch}'...")
        data = {
            "title": title,
            "body": body,
            "head": head_branch,
            "base": base_branch,
            "draft": draft,
        }
        response_data = self._request_and_parse_json(
            "POST", f"/repos/{REPO_SLUG}/pulls", json_payload=data
        )
        pr_url = response_data.get("html_url")
        if not self.runner.dry_run:
            self.runner.print(f"Pull request created: {pr_url}")
        return pr_url

    def get_repo_settings(self) -> dict:
        return self._request_and_parse_json("GET", f"/repos/{REPO_SLUG}")

    def merge_pr(self, pr_url: str) -> Optional[str]:
        if not pr_url:
            return None

        if self.runner.dry_run:
            self.runner.print(f"[Dry Run] Would merge {pr_url}")
            return None

        pr_number_match = re.search(r"/pull/(\d+)", pr_url)
        if not pr_number_match:
            sys.exit(f"Could not extract PR number from URL: {pr_url}")
        pr_number = pr_number_match.group(1)

        head_branch = ""
        max_retries = 10
        retry_delay = 5  # seconds
        for i in range(max_retries):
            self.runner.print(
                f"Attempting to merge {pr_url} (attempt {i+1}/{max_retries})..."
            )

            pr_data = self._request_and_parse_json(
                "GET", f"/repos/{REPO_SLUG}/pulls/{pr_number}"
            )
            head_branch = pr_data["head"]["ref"]

            if pr_data["mergeable"]:
                merge_data = {
                    "merge_method": "squash",
                }
                try:
                    self._request_and_parse_json(
                        "PUT",
                        f"/repos/{REPO_SLUG}/pulls/{pr_number}/merge",
                        json_payload=merge_data,
                    )
                    self.runner.print("Successfully merged.")
                    time.sleep(2)
                    return head_branch
                except urllib.error.HTTPError as e:
                    if e.code == 405:
                        self.runner.print(
                            "PR not mergeable yet. Retrying in "
                            f"{retry_delay} seconds..."
                        )
                        time.sleep(retry_delay)
                    else:
                        raise e
            elif pr_data["mergeable_state"] == "dirty":
                sys.exit("Error: Merge conflict.")
            else:
                self.runner.print(
                    f"PR not mergeable yet ({pr_data['mergeable_state']}). "
                    f"Retrying in {retry_delay} seconds..."
                )
                time.sleep(retry_delay)

        sys.exit(f"Error: PR was not mergeable after {max_retries} attempts.")

    def enable_auto_merge(self, pr_url: str):
        if not pr_url:
            return

        if self.runner.dry_run:
            self.runner.print(f"[Dry Run] Would enable auto-merge for {pr_url}")
            return

        pr_number_match = re.search(r"/pull/(\d+)", pr_url)
        if not pr_number_match:
            sys.exit(f"Could not extract PR number from URL: {pr_url}")
        pr_number = pr_number_match.group(1)

        self.runner.print(f"Enabling auto-merge for {pr_url}...")
        data = {
            "enabled": True,
            "merge_method": "squash",
        }
        self._request_no_content(
            "PUT",
            f"/repos/{REPO_SLUG}/pulls/{pr_number}/auto-merge",
            json_payload=data,
        )
        self.runner.print("Auto-merge enabled.")

    def delete_branch(self, branch_name: str, default_branch: Optional[str] = None):
        if default_branch and branch_name == default_branch:
            self.runner.print(
                f"Error: Refusing to delete the default branch '{branch_name}'.",
                file=sys.stderr,
            )
            return
        try:
            self._request_no_content(
                "DELETE", f"/repos/{REPO_SLUG}/git/refs/heads/{branch_name}"
            )
        except urllib.error.HTTPError as e:
            if e.code == 422:
                self.runner.print(
                    f"Warning: Remote branch '{branch_name}' was already deleted, skipping deletion.",
                    file=sys.stderr,
                )
            else:
                raise e


class LLVMPRAutomator:
    """Automates the process of creating and landing a stack of GitHub Pull Requests."""

    def __init__(
        self,
        args: argparse.Namespace,
        runner: CommandRunner,
        github_api: "GitHubAPI",
        user_login: str,
        token: str,
    ):
        self.args = args
        self.runner = runner
        self.github_api = github_api
        self.user_login = user_login
        self.token = token
        self.original_branch: str = ""
        self.created_branches: List[str] = []
        self.repo_settings: dict = {}

    def _run_cmd(self, command: List[str], read_only: bool = False, **kwargs):
        return self.runner.run_command(command, read_only=read_only, **kwargs)

    def _get_current_branch(self) -> str:
        result = self._run_cmd(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            read_only=True,
        )
        return result.stdout.strip()

    def _check_work_tree_is_clean(self):
        result = self._run_cmd(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            read_only=True,
        )
        if result.stdout.strip():
            sys.exit(
                "Error: Your working tree is dirty. Please stash or commit your changes."
            )

    def _rebase_current_branch(self):
        self._check_work_tree_is_clean()

        target = f"{self.args.upstream_remote}/{self.args.base}"
        self.runner.print(
            f"Fetching from '{self.args.upstream_remote}' and rebasing '{self.original_branch}' on top of '{target}'..."
        )

        authenticated_url = self._get_authenticated_remote_url(
            self.args.upstream_remote
        )
        # Use a refspec to explicitly update the local remote-tracking branch (e.g., origin/main)
        # when fetching from an authenticated URL. This ensures that 'git rebase origin/main'
        # operates on the most up-to-date remote state.
        refspec = f"refs/heads/{self.args.base}:refs/remotes/{self.args.upstream_remote}/{self.args.base}"
        self._run_cmd(["git", "fetch", authenticated_url, refspec])

        try:
            self._run_cmd(["git", "rebase", target])
        except subprocess.CalledProcessError as e:
            self.runner.print(
                "Error: The rebase operation failed, likely due to a merge conflict.",
                file=sys.stderr,
            )
            if e.stdout:
                self.runner.print(f"--- stdout ---\n{e.stdout}", file=sys.stderr)
            if e.stderr:
                self.runner.print(f"--- stderr ---\n{e.stderr}", file=sys.stderr)

            # Check if rebase is in progress before aborting
            rebase_status_result = self._run_cmd(
                ["git", "status", "--verify-status=REBASE_HEAD"],
                check=False,
                capture_output=True,
                text=True,
                read_only=True,
            )

            # REBASE_HEAD exists, so rebase is in progress
            if rebase_status_result.returncode == 0:
                self.runner.print("Aborting rebase...", file=sys.stderr)
                self._run_cmd(["git", "rebase", "--abort"], check=False)
            sys.exit("Error: rebase operation failed.")

    def _get_authenticated_remote_url(self, remote_name: str) -> str:
        """
        Generates an authenticated URL to use for all operations. This includes
        for local operations, like rebaseing after merging a PR in a stack.
        This allows the script to avoid reauthenticating (e.g. via ssh), since
        the token can be reused for all operations.
        """
        remote_url_result = self._run_cmd(
            ["git", "remote", "get-url", remote_name],
            capture_output=True,
            text=True,
            read_only=True,
        )
        remote_url = remote_url_result.stdout.strip()
        if remote_url.startswith("git@github.com:"):
            return remote_url.replace(
                "git@github.com:", f"https://{self.token}@github.com/"
            )
        if remote_url.startswith("https://github.com/"):
            return remote_url.replace("https://", f"https://{self.token}@")
        sys.exit(f"Error: Unsupported remote URL format: {remote_url}")

    def _get_commit_stack(self) -> List[str]:
        target = f"{self.args.upstream_remote}/{self.args.base}"
        merge_base_result = self._run_cmd(
            ["git", "merge-base", "HEAD", target],
            capture_output=True,
            text=True,
            read_only=True,
        )
        merge_base = merge_base_result.stdout.strip()
        if not merge_base:
            sys.exit(f"Error: Could not find a merge base between HEAD and {target}.")

        result = self._run_cmd(
            ["git", "rev-list", "--reverse", f"{merge_base}..HEAD"],
            capture_output=True,
            text=True,
            read_only=True,
        )
        commits = result.stdout.strip().split("\n")
        return [c for c in commits if c]

    def _get_commit_details(self, commit_hash: str) -> tuple[str, str]:
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

    def _sanitize_branch_name(self, text: str) -> str:
        sanitized = re.sub(r"[^\w\s-]", "", text).strip().lower()
        sanitized = re.sub(r"[-\s]+", "-", sanitized)
        # Use "auto-pr" as a fallback.
        return sanitized or "auto-pr"

    def _validate_merge_config(self, num_commits: int) -> None:
        if num_commits > 1:
            if self.args.auto_merge:
                sys.exit("Error: --auto-merge is only supported for a single commit.")

            if self.args.no_merge:
                sys.exit(
                    "Error: --no-merge is only supported for a single commit. "
                    "For stacks, the script must merge sequentially."
                )

        self.runner.print(f"Found {num_commits} commit(s) to process.")

    def _create_and_push_branch_for_commit(
        self, commit_hash: str, base_branch_name: str, index: int
    ) -> str:
        branch_name = f"{self.args.prefix}{base_branch_name}-{index + 1}"
        commit_title, _ = self._get_commit_details(commit_hash)
        self.runner.print(f"Processing commit {commit_hash[:7]}: {commit_title}")
        self.runner.print(f"Pushing commit to temporary branch '{branch_name}'")

        push_url = f"https://{self.token}@github.com/{REPO_SLUG}.git"
        push_command = [
            "git",
            "push",
            push_url,
            f"{commit_hash}:refs/heads/{branch_name}",
        ]
        self._run_cmd(push_command)
        self.created_branches.append(branch_name)
        return branch_name

    def _process_commit(
        self, commit_hash: str, base_branch_name: str, index: int
    ) -> None:
        commit_title, commit_body = self._get_commit_details(commit_hash)

        temp_branch = self._create_and_push_branch_for_commit(
            commit_hash, base_branch_name, index
        )
        pr_url = self.github_api.create_pr(
            head_branch=temp_branch,
            base_branch=self.args.base,
            title=commit_title,
            body=commit_body,
            draft=self.args.draft,
        )

        if not self.args.no_merge:
            if self.args.auto_merge:
                self.github_api.enable_auto_merge(pr_url)
            else:
                merged_branch = self.github_api.merge_pr(pr_url)
                if merged_branch and not self.repo_settings.get(
                    "delete_branch_on_merge"
                ):
                    self.github_api.delete_branch(
                        merged_branch, self.repo_settings.get("default_branch")
                    )
            if temp_branch in self.created_branches:
                self.created_branches.remove(temp_branch)

    def run(self):
        self.repo_settings = self.github_api.get_repo_settings()
        self.original_branch = self._get_current_branch()
        self.runner.print(f"On branch: {self.original_branch}")

        try:
            self._rebase_current_branch()
            commits = self._get_commit_stack()

            if not commits:
                self.runner.print("No new commits to process.")
                return

            self._validate_merge_config(len(commits))
            branch_base_name = self.original_branch
            if self.original_branch == "main":
                first_commit_title, _ = self._get_commit_details(commits[0])
                branch_base_name = self._sanitize_branch_name(first_commit_title)

            for i in range(len(commits)):
                if i > 0:
                    self._rebase_current_branch()

                # After a rebase, the commit hashes change, so we need to get
                # the latest commit stack.
                commits = self._get_commit_stack()
                if not commits:
                    self.runner.print("Success! All commits have been landed.")
                    break
                self._process_commit(commits[0], branch_base_name, i)

        finally:
            self._cleanup()

    def _cleanup(self):
        self.runner.print(f"Returning to original branch: {self.original_branch}")
        self._run_cmd(["git", "checkout", self.original_branch], capture_output=True)
        if self.created_branches:
            self.runner.print("Cleaning up temporary remote branches...")
            delete_url = f"https://{self.token}@github.com/{REPO_SLUG}.git"
            self._run_cmd(
                ["git", "push", delete_url, "--delete"] + self.created_branches,
                check=False,
            )


def check_prerequisites(runner: CommandRunner):
    runner.print("Checking prerequisites...")
    runner.run_command(["git", "--version"], capture_output=True, read_only=True)
    if not os.getenv(LLVM_GITHUB_TOKEN_VAR):
        sys.exit(f"Error: {LLVM_GITHUB_TOKEN_VAR} environment variable not set.")

    result = runner.run_command(
        ["git", "rev-parse", "--is-inside-work-tree"],
        check=False,
        capture_output=True,
        text=True,
        read_only=True,
    )
    if result.returncode != 0 or result.stdout.strip() != "true":
        sys.exit("Error: This script must be run inside a git repository.")
    runner.print("Prerequisites met.")


def main():
    parser = argparse.ArgumentParser(
        description="Create and land a stack of Pull Requests."
    )
    GITHUB_REMOTE_NAME = "origin"
    UPSTREAM_REMOTE_NAME = "upstream"
    BASE_BRANCH = "main"

    command_runner = CommandRunner()
    token = os.getenv(LLVM_GITHUB_TOKEN_VAR)
    default_prefix = "users/"
    user_login = ""
    if token:
        # Create a temporary API client to get the user login.
        # We need the user login for the branch prefix and for creating PRs
        # from a fork. We don't know the repo slug yet, so pass a dummy value.
        temp_api = GitHubAPI(command_runner, token)
        try:
            user_login = temp_api.get_user_login()
            default_prefix = f"{user_login}/"
        except urllib.error.HTTPError as e:
            sys.exit(f"Could not fetch user login from GitHub: {e}")

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
        default=default_prefix,
        help=f"Prefix for temporary branches (default: {default_prefix})",
    )
    parser.add_argument(
        "--draft", action="store_true", help="Create pull requests as drafts."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--no-merge", action="store_true", help="Create PRs but do not merge them."
    )
    group.add_argument(
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
        "-q",
        "--quiet",
        action="store_true",
        help="Print only essential output and errors.",
    )

    args = parser.parse_args()
    if args.prefix and not args.prefix.endswith("/"):
        args.prefix += "/"

    command_runner = CommandRunner(
        dry_run=args.dry_run, verbose=args.verbose, quiet=args.quiet
    )
    check_prerequisites(command_runner)

    github_api = GitHubAPI(command_runner, token)
    automator = LLVMPRAutomator(args, command_runner, github_api, user_login, token)
    automator.run()


if __name__ == "__main__":
    main()
