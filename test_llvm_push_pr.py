import unittest
from unittest.mock import MagicMock, patch, call
import argparse
import subprocess
import requests
import sys

from llvm_push_pr import (
    LLVMPRAutomator,
    Printer,
    GitHubAPI,
    check_prerequisites,
    main,
)


class TestMain(unittest.TestCase):
    @patch("sys.argv", ["llvm_push_pr.py"])
    @patch("llvm_push_pr.check_prerequisites")
    @patch("llvm_push_pr.Printer")
    @patch("llvm_push_pr.GitHubAPI")
    @patch("os.getenv", return_value="test_token")
    def test_main_get_user_login_error(
        self, mock_getenv, mock_github_api_class, mock_printer_class, mock_check_prereqs
    ):
        """Test that main handles errors when fetching user login."""
        mock_github_api_instance = mock_github_api_class.return_value
        mock_github_api_instance.get_user_login.side_effect = (
            requests.exceptions.RequestException
        )

        mock_printer_instance = mock_printer_class.return_value

        mock_automator_instance = MagicMock(spec=LLVMPRAutomator)

        mock_completed_process_repo_slug = MagicMock(spec=subprocess.CompletedProcess)
        mock_completed_process_repo_slug.stdout = "https://github.com/test/repo.git"

        mock_completed_process_clean_tree = MagicMock(spec=subprocess.CompletedProcess)
        mock_completed_process_clean_tree.stdout = ""

        mock_printer_instance.run_command.side_effect = [
            mock_completed_process_repo_slug,  # For _get_repo_slug
            mock_completed_process_clean_tree,  # For _check_work_tree_is_clean
        ]

        with patch(
            "llvm_push_pr.LLVMPRAutomator", return_value=mock_automator_instance
        ):
            main()
            mock_printer_instance.print.assert_called_with(
                "Could not fetch user login from GitHub: ",
                file=sys.stderr,
            )

    @patch("sys.argv", ["llvm_push_pr.py"])
    @patch("llvm_push_pr.check_prerequisites")
    @patch("llvm_push_pr.Printer")
    def test_main_repo_slug_error(self, mock_printer_class, mock_check_prereqs):
        """Test that main exits if the repo slug cannot be parsed."""
        mock_printer_instance = mock_printer_class.return_value
        mock_completed_process = MagicMock()
        mock_completed_process.stdout.strip.return_value = "invalid_url"
        mock_printer_instance.run_command.return_value = mock_completed_process

        with self.assertRaises(SystemExit):
            main()

    @patch("sys.argv", ["llvm_push_pr.py"])
    @patch("llvm_push_pr.check_prerequisites")
    @patch("llvm_push_pr.LLVMPRAutomator")
    @patch("llvm_push_pr.GitHubAPI")
    @patch("llvm_push_pr.Printer")
    def test_main(
        self, mock_printer_class, mock_github_api, mock_automator, mock_check_prereqs
    ):
        """Test the main function."""
        mock_printer_instance = mock_printer_class.return_value
        mock_completed_process = MagicMock()
        mock_completed_process.stdout.strip.return_value = (
            "git@github.com:test/repo.git"
        )
        mock_printer_instance.run_command.return_value = mock_completed_process

        main()
        mock_automator.assert_called_once()
        mock_automator.return_value.run.assert_called_once()


class TestCheckPrerequisites(unittest.TestCase):
    @patch("os.getenv", return_value="test_token")
    def test_not_in_git_repo(self, mock_getenv):
        """Test that check_prerequisites exits if not in a git repo."""
        mock_printer = MagicMock(spec=Printer)
        mock_printer.run_command.side_effect = [
            subprocess.CompletedProcess([], 0, ""),  # git --version
            subprocess.CompletedProcess([], 1, "not a git repo"),  # git rev-parse
        ]
        with self.assertRaises(SystemExit):
            check_prerequisites(mock_printer)

    @patch("llvm_push_pr.Printer.run_command")
    @patch("os.getenv", return_value="test_token")
    def test_git_not_installed(self, mock_getenv, mock_run_command):
        """Test that check_prerequisites exits if git is not installed."""
        mock_run_command.side_effect = FileNotFoundError
        mock_printer = MagicMock(spec=Printer)
        with self.assertRaises(SystemExit):
            check_prerequisites(mock_printer)

    @patch("llvm_push_pr.Printer.run_command")
    @patch("os.getenv", return_value=None)
    def test_no_github_token(self, mock_getenv, mock_run_command):
        """Test that check_prerequisites exits if GITHUB_TOKEN is not set."""
        mock_printer = MagicMock(spec=Printer)
        with self.assertRaises(SystemExit):
            check_prerequisites(mock_printer)


class TestPrinter(unittest.TestCase):
    def test_print_quiet(self):
        """Test that print does not output to stdout in quiet mode."""
        with patch("builtins.print") as mock_print:
            printer = Printer(quiet=True)
            printer.print("test message")
            mock_print.assert_not_called()

    def test_run_command_file_not_found(self):
        """Test that run_command exits if the command is not found."""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            printer = Printer()
            with self.assertRaises(SystemExit):
                printer.run_command(["non_existent_command"])

    def test_run_command_check_false(self):
        """Test that run_command does not raise an exception when check=False."""
        with patch(
            "subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "cmd"),
        ):
            printer = Printer()
            # Should not raise
            printer.run_command(["false"], check=False)

    def test_run_command_error(self):
        """Test that run_command raises an exception on error."""
        with patch(
            "subprocess.run", side_effect=subprocess.CalledProcessError(1, "cmd")
        ):
            printer = Printer()
            with self.assertRaises(subprocess.CalledProcessError):
                printer.run_command(["false"])


class TestGitHubAPI(unittest.TestCase):
    def setUp(self):
        self.mock_printer = MagicMock(spec=Printer)
        self.mock_printer.verbose = False
        self.mock_printer.dry_run = False
        self.github_api = GitHubAPI("test/repo", self.mock_printer, "test_token")

    @patch("requests.request", side_effect=requests.exceptions.RequestException)
    @patch("sys.exit")
    def test_delete_branch_error(self, mock_sys_exit, mock_request):
        """Test that delete_branch handles request exceptions."""
        self.github_api.delete_branch("test-branch")
        self.mock_printer.print.assert_called_with(
            "Error making API request to https://api.github.com/repos/test/repo/git/refs/heads/test-branch: ",
            file=sys.stderr,
        )
        mock_sys_exit.assert_called_once_with(1)

    @patch("requests.request", side_effect=requests.exceptions.RequestException)
    def test_request_error(self, mock_request):
        """Test that _request exits on a request exception."""
        with self.assertRaises(SystemExit):
            self.github_api._request("get", "/user")

    @patch("requests.request")
    def test_get_user_login(self, mock_request):
        """Test that get_user_login returns the correct login."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"login": "test_user"}
        mock_request.return_value = mock_response

        login = self.github_api.get_user_login()

        self.assertEqual(login, "test_user")
        mock_request.assert_called_once_with(
            "get",
            "https://api.github.com/user",
            headers={
                "Authorization": "token test_token",
                "Accept": "application/vnd.github.v3+json",
            },
            timeout=30,
        )

    @patch("requests.request")
    def test_create_pr(self, mock_request):
        """Test that create_pr returns the correct PR URL."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "html_url": "https://github.com/test/repo/pull/1"
        }
        mock_request.return_value = mock_response

        pr_url = self.github_api.create_pr(
            "feature-branch", "main", "Test PR", "Test Body", False
        )

        self.assertEqual(pr_url, "https://github.com/test/repo/pull/1")

    @patch("requests.request")
    @patch("sys.exit")
    def test_merge_pr_not_mergeable_after_retries(self, mock_sys_exit, mock_request):
        """Test that merge_pr exits if the PR is not mergeable after retries."""
        mock_not_mergeable_response = MagicMock()
        mock_not_mergeable_response.json.return_value = {
            "mergeable": False,
            "mergeable_state": "unstable",
            "head": {"ref": "feature-branch"},
        }
        mock_request.return_value = mock_not_mergeable_response

        with patch("time.sleep"):  # Don't actually sleep
            self.github_api.merge_pr("https://github.com/test/repo/pull/1")

        mock_sys_exit.assert_called_once_with(1)

    @patch("requests.request")
    def test_merge_pr_dirty(self, mock_request):
        """Test that merge_pr exits if the mergeable state is 'dirty'."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "mergeable": False,
            "mergeable_state": "dirty",
            "head": {"ref": "feature-branch"},
        }
        mock_request.return_value = mock_response

        with self.assertRaises(SystemExit):
            self.github_api.merge_pr("https://github.com/test/repo/pull/1")

    def test_merge_pr_invalid_url(self):
        """Test that merge_pr exits if the PR number cannot be parsed."""
        with self.assertRaises(SystemExit):
            self.github_api.merge_pr("invalid_url")

    @patch("requests.request")
    def test_merge_pr_retry(self, mock_request):
        """Test that merge_pr retries if the PR is not initially mergeable."""
        mock_not_mergeable_response = MagicMock()
        mock_not_mergeable_response.json.return_value = {
            "mergeable": False,
            "mergeable_state": "unstable",
            "head": {"ref": "feature-branch"},
        }
        mock_mergeable_response = MagicMock()
        mock_mergeable_response.json.return_value = {
            "mergeable": True,
            "title": "Test PR",
            "head": {"ref": "feature-branch"},
        }
        mock_merge_response = MagicMock()

        mock_request.side_effect = [
            mock_not_mergeable_response,
            mock_mergeable_response,
            mock_merge_response,  # For the merge call
            mock_merge_response,  # For the delete branch call
        ]

        with patch("time.sleep"):  # Don't actually sleep
            self.github_api.merge_pr("https://github.com/test/repo/pull/1")

        self.assertEqual(mock_request.call_count, 4)


class TestLLVMPRAutomator(unittest.TestCase):
    def setUp(self):
        self.args = argparse.Namespace(
            remote="origin",
            upstream_remote="upstream",
            base="main",
            prefix="test/",
            draft=False,
            no_merge=False,
            auto_merge=False,
            dry_run=False,
        )
        self.mock_printer = MagicMock(spec=Printer)
        self.mock_github_api = MagicMock(spec=GitHubAPI)
        self.automator = LLVMPRAutomator(
            self.args, self.mock_printer, self.mock_github_api
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

    def test_get_repo_slug_ssh_url(self):
        """Test that _get_repo_slug parses SSH remote URLs correctly."""
        # Un-mock the method for this test
        del self.automator._get_repo_slug
        self.automator._run_cmd.return_value = subprocess.CompletedProcess(
            [], 0, "git@github.com:test_owner/test_repo.git"
        )

        repo_slug = self.automator._get_repo_slug()

        self.assertEqual(repo_slug, "test_owner/test_repo")

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
                call(["git", "branch", "-f", "test/base-branch-1", "commit1"]),
                call(["git", "push", "origin", "test/base-branch-1"]),
            ]
        )

    def test_rebase_current_branch_conflict(self):
        """Test that _rebase_current_branch exits on rebase conflict."""
        # Un-mock the method for this test
        del self.automator._rebase_current_branch
        self.automator._run_cmd.side_effect = [
            subprocess.CompletedProcess([], 0, ""),  # git status
            subprocess.CompletedProcess([], 0, ""),  # git fetch
            subprocess.CalledProcessError(1, "cmd"),  # git rebase
            subprocess.CompletedProcess([], 0, ""),  # git status (in except block)
            subprocess.CompletedProcess([], 0, ""),  # git rebase --abort
        ]
        with self.assertRaises(SystemExit):
            self.automator._rebase_current_branch()

    def test_check_work_tree_is_clean_dirty(self):
        """Test that _check_work_tree_is_clean exits if the work tree is dirty."""
        self.automator._run_cmd.return_value = subprocess.CompletedProcess(
            [], 0, "M some_file"
        )
        with self.assertRaises(SystemExit):
            self.automator._check_work_tree_is_clean()

    def test_get_repo_slug_error(self):
        """Test that _get_repo_slug exits if the remote URL is invalid."""
        # Un-mock the method for this test
        del self.automator._get_repo_slug
        self.automator._run_cmd.return_value = subprocess.CompletedProcess(
            [], 0, "invalid_url"
        )
        with self.assertRaises(SystemExit):
            self.automator._get_repo_slug()

    def test_sanitize_for_branch_name_fallback(self):
        """Test the fallback case for _sanitize_for_branch_name."""
        self.assertEqual(self.automator._sanitize_for_branch_name("!@#$"), "auto-pr")

    def test_run_with_draft_flag(self):
        """Test that the --draft flag is passed to create_pr."""
        self.args.draft = True
        self.automator._get_commit_stack.return_value = ["commit1"]
        self.automator._get_commit_details.return_value = (
            "Commit 1 Title",
            "Commit 1 Body",
        )
        self.automator._create_and_push_branch_for_commit.return_value = (
            "test/feature-branch-1"
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
            self.automator._sanitize_for_branch_name("Branch with spaces"),
            "branch-with-spaces",
        )
        self.assertEqual(
            self.automator._sanitize_for_branch_name("branch/with/slashes"),
            "branchwithslashes",
        )
        self.assertEqual(
            self.automator._sanitize_for_branch_name("branch-with-special-chars!@#$"),
            "branch-with-special-chars",
        )

    def test_run_with_no_merge(self):
        """Test that --no-merge prevents the script from merging the PR."""
        self.args.no_merge = True
        self.automator._get_commit_stack.return_value = ["commit1"]
        self.automator._get_commit_details.return_value = (
            "Commit 1 Title",
            "Commit 1 Body",
        )
        self.automator._create_and_push_branch_for_commit.return_value = (
            "test/feature-branch-1"
        )

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

        self.automator.run()

        self.assertEqual(self.automator._rebase_current_branch.call_count, 2)
        self.assertEqual(
            self.automator._create_and_push_branch_for_commit.call_count, 2
        )
        self.assertEqual(self.mock_github_api.create_pr.call_count, 2)
        self.assertEqual(self.mock_github_api.merge_pr.call_count, 2)

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

        self.automator._rebase_current_branch.assert_called_once()
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

        self.automator._rebase_current_branch.assert_called_once()
        self.mock_printer.print.assert_called_with("No new commits to process.")
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
                call(["git", "branch", "-D", "branch1", "branch2"]),
                call(
                    [
                        "git",
                        "push",
                        "origin",
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
        with self.assertRaises(SystemExit):
            self.automator._get_commit_stack()

    def test_run_auto_merge_multiple_commits(self):
        """Test that --auto-merge with multiple commits exits."""
        self.args.auto_merge = True
        self.automator._get_commit_stack.return_value = ["commit1", "commit2"]
        with self.assertRaises(SystemExit):
            self.automator.run()

    def test_run_no_merge_multiple_commits(self):
        """Test that --no-merge with multiple commits exits."""
        self.args.no_merge = True
        self.automator._get_commit_stack.return_value = ["commit1", "commit2"]
        with self.assertRaises(SystemExit):
            self.automator.run()


if __name__ == "__main__":
    unittest.main()
