import unittest
from unittest.mock import MagicMock, patch, call
import io
import argparse
import subprocess
import sys
import urllib.request
import urllib.error

from llvm_push_pr import (
    CommandRunner,
    GitHubAPI,
    LLVMPRAutomator,
    check_prerequisites,
    main,
    LlvmPrError,
    PRAutomatorConfig,
)


class TestMain(unittest.TestCase):
    @patch("sys.argv", ["llvm_push_pr.py"])
    @patch("llvm_push_pr.check_prerequisites")
    @patch("llvm_push_pr.CommandRunner")
    @patch("llvm_push_pr.GitHubAPI")
    @patch("os.getenv", return_value="test_token")
    @patch("urllib.request.urlopen")
    def test_main_get_user_login_error(
        self,
        mock_urlopen,
        mock_getenv,
        mock_github_api_class,
        mock_command_runner_class,
        mock_check_prereqs,
    ):
        """Test that main handles errors when fetching user login."""
        mock_github_api_instance = mock_github_api_class.return_value
        mock_github_api_instance.get_user_login.side_effect = urllib.error.HTTPError(
            "url", 404, "Not Found", {}, None
        )

        mock_command_runner_instance = mock_command_runner_class.return_value

        mock_automator_instance = MagicMock(spec=LLVMPRAutomator)

        mock_completed_process_repo_slug = MagicMock(spec=subprocess.CompletedProcess)
        mock_completed_process_repo_slug.stdout = "https://github.com/test/repo.git"

        mock_completed_process_clean_tree = MagicMock(spec=subprocess.CompletedProcess)
        mock_completed_process_clean_tree.stdout = ""

        mock_command_runner_instance.run_command.side_effect = [
            mock_completed_process_repo_slug,  # For _get_repo_slug
            mock_completed_process_clean_tree,  # For _check_work_tree_is_clean
        ]

        with patch(
            "llvm_push_pr.LLVMPRAutomator", return_value=mock_automator_instance
        ):
            with self.assertRaises(LlvmPrError):
                main()

    @patch("sys.argv", ["llvm_push_pr.py"])
    @patch("llvm_push_pr.check_prerequisites")
    @patch("llvm_push_pr.LLVMPRAutomator")
    @patch("llvm_push_pr.GitHubAPI")
    @patch("llvm_push_pr.CommandRunner")
    @patch("os.getenv", return_value="test_token")
    def test_main(
        self,
        mock_getenv,
        mock_command_runner_class,
        mock_github_api,
        mock_automator,
        mock_check_prereqs,
    ):
        """Test the main function."""
        mock_command_runner_instance = mock_command_runner_class.return_value
        mock_completed_process = MagicMock()
        mock_completed_process.stdout.strip.return_value = (
            "git@github.com:test/repo.git"
        )
        mock_command_runner_instance.run_command.return_value = mock_completed_process

        main()
        mock_automator.return_value.run.assert_called_once()


class TestCheckPrerequisites(unittest.TestCase):
    @patch("os.getenv", return_value="test_token")
    def test_not_in_git_repo(self, mock_getenv):
        """Test that check_prerequisites exits if not in a git repo."""
        mock_command_runner = MagicMock(spec=CommandRunner)
        mock_command_runner.run_command.side_effect = [
            subprocess.CompletedProcess([], 0, ""),  # git --version
            subprocess.CompletedProcess([], 1, "not a git repo"),  # git rev-parse
        ]
        with self.assertRaises(LlvmPrError):
            check_prerequisites(mock_command_runner)

    @patch("llvm_push_pr.CommandRunner.run_command")
    @patch("os.getenv", return_value="test_token")
    def test_git_not_installed(self, mock_getenv, mock_run_command):
        """Test that check_prerequisites exits if git is not installed."""
        mock_run_command.side_effect = FileNotFoundError
        mock_command_runner = MagicMock(spec=CommandRunner)
        with self.assertRaises(LlvmPrError):
            check_prerequisites(mock_command_runner)

    @patch("llvm_push_pr.CommandRunner.run_command")
    @patch("os.getenv", return_value=None)
    def test_no_github_token(self, mock_getenv, mock_run_command):
        """Test that check_prerequisites exits if GITHUB_TOKEN is not set."""
        mock_command_runner = MagicMock(spec=CommandRunner)
        with self.assertRaises(LlvmPrError):
            check_prerequisites(mock_command_runner)


class TestCommandRunner(unittest.TestCase):
    def test_print_quiet(self):
        """Test that print does not output to stdout in quiet mode."""
        with patch("builtins.print") as mock_print:
            command_runner = CommandRunner(quiet=True)
            command_runner.print("test message")
            mock_print.assert_not_called()

    def test_run_command_file_not_found(self):
        """Test that run_command exits if the command is not found."""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            command_runner = CommandRunner()
            with self.assertRaises(SystemExit):
                command_runner.run_command(["non_existent_command"])

    def test_run_command_check_false(self):
        """Test that run_command does not raise an exception when check=False."""
        command_runner = CommandRunner()
        # The `false` command exists with a non-zero status code.
        result = command_runner.run_command(["false"], check=False)
        self.assertIsInstance(result, subprocess.CompletedProcess)
        self.assertNotEqual(result.returncode, 0)

    def test_run_command_error(self):
        """Test that run_command raises an exception on error."""
        command_runner = CommandRunner()
        with self.assertRaises(subprocess.CalledProcessError):
            # The `false` command exists with a non-zero status code, which should raise
            # an exception when check=True (the default).
            command_runner.run_command(["false"])


class TestGitHubAPI(unittest.TestCase):
    def setUp(self):
        self.mock_command_runner = MagicMock(spec=CommandRunner)
        self.mock_command_runner.verbose = False
        self.mock_command_runner.dry_run = False
        self.github_api = GitHubAPI(self.mock_command_runner, "test_token")
        # Mock the opener to prevent real network calls.
        self.github_api.opener = MagicMock()

    def test_delete_branch_already_deleted(self):
        """Test that delete_branch handles a 422 error."""
        mock_error = urllib.error.HTTPError(
            "url",
            422,
            "Reference does not exist",
            {},
            io.BytesIO(b"Reference does not exist"),
        )
        self.github_api.opener.open.side_effect = mock_error

        self.mock_command_runner.verbose = True
        self.github_api.delete_branch("already-deleted-branch")
        expected_calls = [
            call(
                "API Request: DELETE https://api.github.com/repos/ilovepi/llvm-push-pr/git/refs/heads/already-deleted-branch"
            ),
            call(
                "Error making API request to https://api.github.com/repos/ilovepi/llvm-push-pr/git/refs/heads/already-deleted-branch: HTTP Error 422: Reference does not exist",
                file=sys.stderr,
            ),
            call(
                "Error response body: Reference does not exist",
                file=sys.stderr,
            ),
            call(
                "Warning: Remote branch 'already-deleted-branch' was already deleted, skipping deletion.",
                file=sys.stderr,
            ),
        ]
        self.mock_command_runner.print.assert_has_calls(expected_calls)

    def test_delete_branch_error(self):
        """Test that delete_branch handles request exceptions."""
        mock_error = urllib.error.HTTPError(
            "url", 500, "Internal Server Error", {}, None
        )
        self.github_api.opener.open.side_effect = mock_error
        with self.assertRaises(urllib.error.HTTPError):
            self.github_api.delete_branch("test-branch")
        self.mock_command_runner.print.assert_called_with(
            "Error making API request to https://api.github.com/repos/ilovepi/llvm-push-pr/git/refs/heads/test-branch: HTTP Error 500: Internal Server Error",
            file=sys.stderr,
        )

    def test_request_error(self):
        """Test that _request raises on a request exception."""
        mock_error = urllib.error.HTTPError(
            "url", 500, "Internal Server Error", {}, None
        )
        self.github_api.opener.open.side_effect = mock_error
        with self.assertRaises(urllib.error.HTTPError):
            self.github_api._request("get", "/user")

    def test_get_user_login(self):
        """Test that get_user_login returns the correct login."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"login": "test_user"}'
        self.github_api.opener.open.return_value.__enter__.return_value = mock_response
        login = self.github_api.get_user_login()
        self.assertEqual(login, "test_user")
        self.github_api.opener.open.assert_called_once()

    def test_create_pr(self):
        """Test that create_pr returns the correct PR URL."""
        mock_response = MagicMock()
        mock_response.read.return_value = (
            b'{"html_url": "https://github.com/test/repo/pull/1"}'
        )
        self.github_api.opener.open.return_value.__enter__.return_value = mock_response
        pr_url = self.github_api.create_pr(
            "feature-branch", "main", "Test PR", "Test Body", False
        )
        self.assertEqual(pr_url, "https://github.com/test/repo/pull/1")

    def test_merge_pr_not_mergeable_after_retries(self):
        """Test that merge_pr raises an exception if the PR is not mergeable after retries."""
        mock_not_mergeable_response = MagicMock()
        mock_not_mergeable_response.read.return_value = b'{"mergeable": false, "mergeable_state": "unstable", "head": {"ref": "feature-branch"}}'
        self.github_api.opener.open.return_value.__enter__.return_value = (
            mock_not_mergeable_response
        )
        with patch("time.sleep"):  # Don't actually sleep
            with self.assertRaisesRegex(
                LlvmPrError, "PR was not mergeable after 10 attempts."
            ):
                self.github_api.merge_pr("https://github.com/test/repo/pull/1")

    def test_merge_pr_dirty(self):
        """Test that merge_pr exits if the mergeable state is 'dirty'."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"mergeable": false, "mergeable_state": "dirty", "head": {"ref": "feature-branch"}}'
        self.github_api.opener.open.return_value.__enter__.return_value = mock_response
        with self.assertRaises(LlvmPrError):
            self.github_api.merge_pr("https://github.com/test/repo/pull/1")

    def test_merge_pr_invalid_url(self):
        """Test that merge_pr exits if the PR number cannot be parsed."""
        with self.assertRaises(LlvmPrError):
            self.github_api.merge_pr("invalid_url")

    def test_merge_pr_405_retry(self):
        """Test that merge_pr retries on a 405 error."""
        mock_mergeable_response = MagicMock()
        mock_mergeable_response.read.return_value.decode.return_value = (
            '{"mergeable": true, "title": "Test PR", "head": {"ref": "feature-branch"}}'
        )

        mock_405_error = urllib.error.HTTPError(
            "url", 405, "Method Not Allowed", {}, io.BytesIO(b"Method Not Allowed")
        )

        mock_success_response = MagicMock()
        mock_success_response.read.return_value.decode.return_value = "{}"

        self.github_api.opener.open.side_effect = [
            MagicMock(__enter__=MagicMock(return_value=mock_mergeable_response)),
            mock_405_error,
            MagicMock(__enter__=MagicMock(return_value=mock_mergeable_response)),
            MagicMock(__enter__=MagicMock(return_value=mock_success_response)),
        ]
        with patch("time.sleep"):  # Don't actually sleep
            self.github_api.merge_pr("https://github.com/test/repo/pull/1")

        self.assertEqual(self.github_api.opener.open.call_count, 4)

    def test_merge_pr_retry(self):
        """Test that merge_pr retries if the PR is not initially mergeable."""
        mock_not_mergeable_response = MagicMock()
        mock_not_mergeable_response.read.return_value.decode.return_value = '{"mergeable": false, "mergeable_state": "unstable", "head": {"ref": "feature-branch"}}'
        mock_mergeable_response = MagicMock()
        mock_mergeable_response.read.return_value.decode.return_value = (
            '{"mergeable": true, "title": "Test PR", "head": {"ref": "feature-branch"}}'
        )
        mock_merge_response = MagicMock()
        mock_merge_response.read.return_value.decode.return_value = "{}"

        self.github_api.opener.open.side_effect = [
            MagicMock(__enter__=MagicMock(return_value=mock_not_mergeable_response)),
            MagicMock(__enter__=MagicMock(return_value=mock_mergeable_response)),
            MagicMock(__enter__=MagicMock(return_value=mock_merge_response)),
        ]
        with patch("time.sleep"):  # Don't actually sleep
            self.github_api.merge_pr("https://github.com/test/repo/pull/1")

        self.assertEqual(self.github_api.opener.open.call_count, 3)


class TestLLVMPRAutomator(unittest.TestCase):
    def setUp(self):
        self.mock_command_runner = MagicMock(spec=CommandRunner)
        self.mock_github_api = MagicMock(spec=GitHubAPI)
        self.config = PRAutomatorConfig(
            user_login="test_user",
            token="test_token",
            base_branch="main",
            upstream_remote="upstream",
            prefix="test/",
            draft=False,
            no_merge=False,
            auto_merge=False,
        )
        self.automator = LLVMPRAutomator(
            runner=self.mock_command_runner,
            github_api=self.mock_github_api,
            config=self.config,
        )
        self.automator.original_branch = "feature-branch"
        # Mock the git commands that are not part of the GitHubAPI
        self.automator._run_cmd = MagicMock()
        self.automator._get_repo_slug = MagicMock(return_value="test/repo")
        self.automator._get_current_branch = MagicMock(return_value="feature-branch")
        self.automator._get_commit_stack = MagicMock()
        self.automator._get_commit_details = MagicMock()
        self.automator._rebase_current_branch = MagicMock()
        self.automator._create_and_push_branch_for_commit = MagicMock()
        self.automator._cleanup = MagicMock()

    def test_get_current_branch_empty(self):
        """Test that _get_current_branch handles empty git rev-parse output."""
        # Un-mock the method for this test
        del self.automator._get_current_branch
        self.automator._run_cmd.return_value = subprocess.CompletedProcess([], 0, "")

        branch = self.automator._get_current_branch()

        self.assertEqual(branch, "")

    def test_get_commit_stack_empty_rev_list(self):
        """Test that _get_commit_stack handles empty git rev-list output."""
        # Un-mock the method for this test
        del self.automator._get_commit_stack
        self.automator._run_cmd.side_effect = [
            subprocess.CompletedProcess([], 0, "merge_base_hash"),  # git merge-base
            subprocess.CompletedProcess([], 0, ""),  # git rev-list
        ]

        commits = self.automator._get_commit_stack()

        self.assertEqual(commits, [])

    def test_run_main_branch_name_from_commit(self):
        """Test that run uses commit title for branch name on main branch."""
        self.automator.original_branch = "main"
        self.automator._get_current_branch.return_value = "main"
        self.automator._get_commit_stack.return_value = ["commit1"]
        self.automator._get_commit_details.return_value = ("Feature Title", "Body")
        self.automator._create_and_push_branch_for_commit.return_value = (
            "test/feature-title-1"
        )
        self.mock_github_api.create_pr.return_value = (
            "https://github.com/test/repo/pull/1"
        )

        self.automator.run()

        self.automator._create_and_push_branch_for_commit.assert_called_once_with(
            "commit1", "feature-title", 0
        )

    def test_get_commit_details_no_body(self):
        """Test that _get_commit_details handles commits with no body."""
        # Un-mock the method for this test
        del self.automator._get_commit_details
        self.automator._run_cmd.return_value = subprocess.CompletedProcess(
            [], 0, "Commit Title\n"
        )

        title, body = self.automator._get_commit_details("commit1")

        self.assertEqual(title, "Commit Title")
        self.assertEqual(body, "")

    def test_create_and_push_branch_for_commit_empty_title(self):
        """Test that _create_and_push_branch_for_commit handles empty commit title."""
        # Un-mock the method for this test
        del self.automator._create_and_push_branch_for_commit
        self.automator._get_commit_details.return_value = ("", "")
        self.automator._run_cmd = MagicMock()

        branch_name = self.automator._create_and_push_branch_for_commit(
            "commit1", "base-branch", 0
        )

        self.assertEqual(branch_name, "test/base-branch-1")
        self.automator._run_cmd.assert_has_calls(
            [
                call(
                    [
                        "git",
                        "push",
                        "https://test_token@github.com/ilovepi/llvm-push-pr.git",
                        "commit1:refs/heads/test/base-branch-1",
                    ]
                ),
            ]
        )

    def test_rebase_current_branch_conflict_no_rebase_in_progress(self):
        """Test that _rebase_current_branch exits on rebase conflict when no rebase is in progress."""
        # Un-mock the method for this test
        del self.automator._rebase_current_branch
        self.automator._run_cmd.side_effect = [
            subprocess.CompletedProcess([], 0, ""),  # git status
            subprocess.CompletedProcess(
                [], 0, "git@github.com:upstream/repo.git"
            ),  # git remote get-url
            subprocess.CompletedProcess([], 0, ""),  # git fetch
            subprocess.CalledProcessError(1, "cmd"),  # git rebase
            subprocess.CompletedProcess(
                [], 1, ""
            ),  # git status (in except block, no rebase in progress)
        ]
        with self.assertRaises(LlvmPrError):
            self.automator._rebase_current_branch()
        self.automator._run_cmd.assert_has_calls(
            [
                call(
                    [
                        "git",
                        "fetch",
                        "https://test_token@github.com/upstream/repo.git",
                        "refs/heads/main:refs/remotes/upstream/main",
                    ]
                )
            ],
            any_order=True,
        )

    def test_rebase_current_branch_conflict(self):
        """Test that _rebase_current_branch exits on rebase conflict."""
        # Un-mock the method for this test
        del self.automator._rebase_current_branch
        self.automator._run_cmd.side_effect = [
            subprocess.CompletedProcess([], 0, ""),  # git status
            subprocess.CompletedProcess(
                [], 0, "git@github.com:upstream/repo.git"
            ),  # git remote get-url
            subprocess.CompletedProcess([], 0, ""),  # git fetch
            subprocess.CalledProcessError(1, "cmd"),  # git rebase
            subprocess.CompletedProcess([], 0, ""),  # git status (in except block)
            subprocess.CompletedProcess([], 0, ""),  # git rebase --abort
        ]
        with self.assertRaises(LlvmPrError):
            self.automator._rebase_current_branch()
        self.automator._run_cmd.assert_has_calls(
            [
                call(
                    [
                        "git",
                        "fetch",
                        "https://test_token@github.com/upstream/repo.git",
                        "refs/heads/main:refs/remotes/upstream/main",
                    ]
                )
            ],
            any_order=True,
        )

    def test_check_work_tree_is_clean_dirty(self):
        """Test that _check_work_tree_is_clean exits if the work tree is dirty."""
        self.automator._run_cmd.return_value = subprocess.CompletedProcess(
            [], 0, "M some_file"
        )
        with self.assertRaises(LlvmPrError):
            self.automator._check_work_tree()

    def test_sanitize_for_branch_name_fallback(self):
        """Test the fallback case for _sanitize_for_branch_name."""
        self.assertEqual(self.automator._sanitize_branch_name("!@#$"), "auto-pr")
        self.config.draft = True
        self.automator = LLVMPRAutomator(
            runner=self.mock_command_runner,
            github_api=self.mock_github_api,
            config=self.config,
        )
        self.automator._run_cmd = MagicMock()
        self.automator._rebase_current_branch = MagicMock()
        self.automator._get_commit_stack = MagicMock(return_value=["commit1"])
        self.automator._get_commit_details = MagicMock(
            return_value=("Commit 1 Title", "Commit 1 Body")
        )
        self.automator._create_and_push_branch_for_commit = MagicMock(
            return_value="test/feature-branch-1"
        )

        self.automator.run()

        self.mock_github_api.create_pr.assert_called_once_with(
            head_branch="test/feature-branch-1",
            base_branch="main",
            title="Commit 1 Title",
            body="Commit 1 Body",
            draft=True,
        )

    def test_sanitize_for_branch_name(self):
        """Test that branch names are sanitized correctly."""
        self.assertEqual(
            self.automator._sanitize_branch_name("Branch with spaces"),
            "branch-with-spaces",
        )
        self.assertEqual(
            self.automator._sanitize_branch_name("branch/with/slashes"),
            "branchwithslashes",
        )
        self.assertEqual(
            self.automator._sanitize_branch_name("branch-with-special-chars!@#$"),
            "branch-with-special-chars",
        )

    def test_run_with_no_merge(self):
        self.config.no_merge = True
        self.automator = LLVMPRAutomator(
            runner=self.mock_command_runner,
            github_api=self.mock_github_api,
            config=self.config,
        )
        self.automator._run_cmd = MagicMock()
        self.automator._rebase_current_branch = MagicMock()
        self.automator._get_commit_stack = MagicMock(return_value=["commit1"])
        self.automator._get_commit_details = MagicMock(
            return_value=("Commit 1 Title", "Commit 1 Body")
        )
        self.automator._create_and_push_branch_for_commit = MagicMock(
            return_value="test/feature-branch-1"
        )

        self.automator._cleanup = MagicMock()
        self.automator.run()

        self.mock_github_api.create_pr.assert_called_once()
        self.mock_github_api.merge_pr.assert_not_called()
        self.automator._cleanup.assert_called_once()

    def test_run_multiple_commits(self):
        """Test the script with a stack of multiple commits."""
        self.automator._get_commit_stack.side_effect = [
            ["commit1", "commit2"],  # initial_commits
            ["commit1", "commit2"],  # commits for i=0
            ["commit2"],  # commits for i=1
            [],  # commits for i=2 (loop terminates)
        ]
        self.automator._get_commit_details.side_effect = [
            ("Commit 1 Title", "Commit 1 Body"),
            ("Commit 2 Title", "Commit 2 Body"),
        ]
        self.automator._create_and_push_branch_for_commit.side_effect = [
            "test/feature-branch-1",
            "test/feature-branch-2",
        ]
        self.mock_github_api.create_pr.side_effect = [
            "https://github.com/test/repo/pull/1",
            "https://github.com/test/repo/pull/2",
        ]
        self.mock_github_api.merge_pr.side_effect = [
            "test/feature-branch-1",
            "test/feature-branch-2",
        ]
        self.mock_github_api.delete_branch = MagicMock()
        self.automator.repo_settings = {"delete_branch_on_merge": False}
        self.mock_github_api.get_repo_settings = MagicMock(
            return_value={"delete_branch_on_merge": False}
        )

        self.automator.run()

        self.assertEqual(self.automator._rebase_current_branch.call_count, 2)
        self.assertEqual(
            self.automator._create_and_push_branch_for_commit.call_count, 2
        )
        self.assertEqual(self.mock_github_api.create_pr.call_count, 2)
        self.assertEqual(self.mock_github_api.merge_pr.call_count, 2)
        self.assertEqual(self.mock_github_api.delete_branch.call_count, 2)

        # Verify the calls were made in the correct order
        self.automator._create_and_push_branch_for_commit.assert_has_calls(
            [
                call("commit1", "feature-branch", 0),
                call("commit2", "feature-branch", 1),
            ]
        )
        self.mock_github_api.create_pr.assert_has_calls(
            [
                call(
                    head_branch="test/feature-branch-1",
                    base_branch="main",
                    title="Commit 1 Title",
                    body="Commit 1 Body",
                    draft=False,
                ),
                call(
                    head_branch="test/feature-branch-2",
                    base_branch="main",
                    title="Commit 2 Title",
                    body="Commit 2 Body",
                    draft=False,
                ),
            ]
        )
        self.mock_github_api.merge_pr.assert_has_calls(
            [
                call("https://github.com/test/repo/pull/1"),
                call("https://github.com/test/repo/pull/2"),
            ]
        )
        self.mock_github_api.delete_branch.assert_has_calls(
            [
                call("test/feature-branch-1", None),
                call("test/feature-branch-2", None),
            ]
        )
        self.automator._cleanup.assert_called_once()

    def test_run_single_commit(self):
        """Test the script with a single commit."""
        self.automator._get_commit_stack.return_value = ["commit1"]
        self.automator._get_commit_details.return_value = (
            "Commit 1 Title",
            "Commit 1 Body",
        )
        self.automator._create_and_push_branch_for_commit.return_value = (
            "test/feature-branch-1"
        )
        self.mock_github_api.create_pr.return_value = (
            "https://github.com/test/repo/pull/1"
        )

        self.automator.run()
        self.automator._create_and_push_branch_for_commit.assert_called_once_with(
            "commit1", "feature-branch", 0
        )
        self.mock_github_api.create_pr.assert_called_once_with(
            head_branch="test/feature-branch-1",
            base_branch="main",
            title="Commit 1 Title",
            body="Commit 1 Body",
            draft=False,
        )
        self.mock_github_api.merge_pr.assert_called_once_with(
            "https://github.com/test/repo/pull/1"
        )
        self.automator._cleanup.assert_called_once()

    def test_run_no_new_commits(self):
        """Test that the script exits gracefully when there are no new commits."""
        self.automator._get_commit_stack.return_value = []

        self.automator.run()

        self.mock_command_runner.print.assert_called_with("No new commits to process.")
        self.mock_github_api.create_pr.assert_not_called()
        self.automator._cleanup.assert_called_once()

    def test_cleanup_with_branches(self):
        """Test that _cleanup deletes created branches."""
        # Un-mock the method for this test
        del self.automator._cleanup
        self.automator.created_branches = ["branch1", "branch2"]
        self.automator._run_cmd = MagicMock()

        self.automator._cleanup()

        self.automator._run_cmd.assert_has_calls(
            [
                call(["git", "checkout", "feature-branch"], capture_output=True),
                call(
                    [
                        "git",
                        "push",
                        "https://test_token@github.com/ilovepi/llvm-push-pr.git",
                        "--delete",
                        "branch1",
                        "branch2",
                    ],
                    check=False,
                ),
            ]
        )

    def test_cleanup_no_branches(self):
        """Test that _cleanup does not try to delete branches if none were created."""
        # Un-mock the method for this test
        del self.automator._cleanup
        self.automator.created_branches = []
        self.automator._run_cmd = MagicMock()

        self.automator._cleanup()

        self.automator._run_cmd.assert_called_once_with(
            ["git", "checkout", "feature-branch"], capture_output=True
        )

    def test_get_commit_stack_no_merge_base(self):
        """Test that _get_commit_stack exits if no merge base is found."""
        # Un-mock the method for this test
        del self.automator._get_commit_stack
        self.automator._run_cmd.return_value = subprocess.CompletedProcess([], 0, "")
        with self.assertRaises(LlvmPrError):
            self.automator._get_commit_stack()

    def test_run_auto_merge_multiple_commits(self):
        """Test that --auto-merge with multiple commits exits."""
        self.automator = LLVMPRAutomator(
            runner=self.mock_command_runner,
            github_api=self.mock_github_api,
            config=self.config,
        )
        self.automator._get_commit_details = MagicMock(
            return_value=("Commit Title", "Commit Body")
        )
        self.automator._get_commit_stack = MagicMock(
            return_value=["commit1", "commit2"]
        )
        with self.assertRaises(LlvmPrError):
            self.automator.run()

    def test_run_no_merge_multiple_commits(self):
        """Test that --no-merge with multiple commits exits."""
        self.config.no_merge = True
        self.automator = LLVMPRAutomator(
            runner=self.mock_command_runner,
            github_api=self.mock_github_api,
            config=self.config,
        )
        self.automator._get_commit_details = MagicMock(
            return_value=("Commit Title", "Commit Body")
        )
        self.automator._get_commit_stack = MagicMock(
            return_value=["commit1", "commit2"]
        )
        with self.assertRaises(LlvmPrError):
            self.automator.run()


if __name__ == "__main__":
    unittest.main()


class TestNewFeatures(unittest.TestCase):
    def setUp(self):
        self.mock_command_runner = MagicMock(spec=CommandRunner)
        self.mock_command_runner.verbose = False
        self.mock_command_runner.dry_run = False
        self.github_api = GitHubAPI(self.mock_command_runner, "test_token")
        self.github_api.opener = MagicMock()  # Mock the opener
        self.config = PRAutomatorConfig(
            user_login="test_user",
            token="test_token",
            base_branch="main",
            upstream_remote="upstream",
            prefix="test/",
            draft=False,
            no_merge=False,
            auto_merge=False,
        )
        self.automator = LLVMPRAutomator(
            runner=self.mock_command_runner,
            github_api=self.github_api,
            config=self.config,
        )
        self.automator._run_cmd = MagicMock()
        self.automator._get_repo_slug = MagicMock(return_value="test/repo")
        self.automator._get_current_branch = MagicMock(return_value="feature-branch")
        self.automator._get_commit_stack = MagicMock()
        self.automator._get_commit_details = MagicMock()
        self.automator._rebase_current_branch = MagicMock()
        self.automator._create_and_push_branch_for_commit = MagicMock()
        self.automator._cleanup = MagicMock()

    def test_get_repo_settings(self):
        """Test that get_repo_settings returns the correct settings."""
        mock_response = MagicMock()
        mock_response.read.return_value = (
            b'{"delete_branch_on_merge": true, "default_branch": "main"}'
        )
        self.github_api.opener.open.return_value.__enter__.return_value = mock_response
        settings = self.github_api.get_repo_settings()
        self.assertEqual(settings["delete_branch_on_merge"], True)
        self.assertEqual(settings["default_branch"], "main")
        self.github_api.opener.open.assert_called_once()

    def test_enable_auto_merge(self):
        """Test that enable_auto_merge sends the correct request."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"{}"
        self.github_api.opener.open.return_value.__enter__.return_value = mock_response
        self.github_api.enable_auto_merge("https://github.com/test/repo/pull/1")
        self.github_api.opener.open.assert_called_once()

    def test_delete_branch_refuses_default(self):
        """Test that delete_branch refuses to delete the default branch."""
        self.github_api.delete_branch("main", "main")
        self.mock_command_runner.print.assert_called_with(
            "Error: Refusing to delete the default branch 'main'.",
            file=sys.stderr,
        )

    def test_run_with_auto_merge(self):
        """Test that --auto-merge calls enable_auto_merge."""
        self.config.auto_merge = True
        self.automator = LLVMPRAutomator(
            runner=self.mock_command_runner,
            github_api=self.github_api,
            config=self.config,
        )
        self.automator._run_cmd = MagicMock()
        self.automator._rebase_current_branch = MagicMock()
        self.automator._get_commit_stack = MagicMock(return_value=["commit1"])
        self.automator._get_commit_details = MagicMock(
            return_value=("Title", "Body")
        )
        self.automator._create_and_push_branch_for_commit = MagicMock(
            return_value="test/branch"
        )
        self.github_api.create_pr = MagicMock(
            return_value="https://github.com/test/repo/pull/1"
        )
        self.github_api.enable_auto_merge = MagicMock()
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"head": {"ref": "test/branch"}, "mergeable": true}'
        self.github_api.opener.open.return_value.__enter__.return_value = mock_response

        self.automator.run()

        self.github_api.enable_auto_merge.assert_called_once_with(
            "https://github.com/test/repo/pull/1"
        )

    def test_run_avoids_deleting_branch_when_repo_auto_deletes(self):
        """Test that run does not delete branch if repo is set to auto-delete."""
        self.automator._get_commit_stack.return_value = ["commit1"]
        self.automator._get_commit_details.return_value = ("Title", "Body")
        self.automator._create_and_push_branch_for_commit.return_value = "test/branch"
        self.github_api.create_pr = MagicMock(
            return_value="https://github.com/test/repo/pull/1"
        )
        self.github_api.merge_pr = MagicMock(return_value="test/branch")
        self.github_api.delete_branch = MagicMock()
        self.github_api.get_repo_settings = MagicMock(
            return_value={"delete_branch_on_merge": True, "default_branch": "main"}
        )

        self.automator.run()

        self.github_api.merge_pr.assert_called_once()
        self.github_api.delete_branch.assert_not_called()

    def test_run_deletes_branch_when_repo_does_not_auto_delete(self):
        """Test that run deletes branch if repo is not set to auto-delete."""
        self.automator._get_commit_stack.return_value = ["commit1"]
        self.automator._get_commit_details.return_value = ("Title", "Body")
        self.automator._create_and_push_branch_for_commit.return_value = "test/branch"
        self.github_api.create_pr = MagicMock(
            return_value="https://github.com/test/repo/pull/1"
        )
        self.github_api.merge_pr = MagicMock(return_value="test/branch")
        self.github_api.delete_branch = MagicMock()
        self.github_api.get_repo_settings = MagicMock(
            return_value={"delete_branch_on_merge": False, "default_branch": "main"}
        )

        self.automator.run()

        self.github_api.merge_pr.assert_called_once()
        self.github_api.delete_branch.assert_called_once_with("test/branch", "main")
