
import subprocess
import shutil
from unittest.mock import MagicMock, patch
import pytest
from rich.console import Console

from services.setup._cli_tools import NodeCheck, _is_macos

@pytest.fixture
def console():
    return MagicMock(spec=Console)

class TestNodeCheckRobustness:
    """High-signal tests for Node.js version validation and installation logic."""

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_node_version_too_old(self, mock_run, mock_which):
        """Should return False if Node.js < 18."""
        mock_which.return_value = "/usr/bin/node"
        # v16.0.0 is too old
        mock_run.return_value = MagicMock(stdout="v16.0.0\n", returncode=0)
        
        check = NodeCheck()
        assert check.check() is False

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_node_version_valid(self, mock_run, mock_which):
        """Should return True if Node.js >= 18."""
        mock_which.return_value = "/usr/bin/node"
        mock_run.return_value = MagicMock(stdout="v20.5.0\n", returncode=0)
        
        check = NodeCheck()
        assert check.check() is True

    @patch("services.setup._cli_tools._is_macos", return_value=True)
    @patch("services.setup._cli_tools._ensure_macports", return_value=True)
    @patch("subprocess.run")
    def test_node_install_macos_prefers_macports(self, mock_run, mock_mp, mock_macos, console):
        """On macOS, if MacPorts is available, it should be used for Node.js."""
        mock_run.return_value = MagicMock(returncode=0)
        check = NodeCheck()
        assert check.install(console) is True
        mock_run.assert_called_with(["sudo", "port", "install", "nodejs20"], check=True, text=True)

    @patch("services.setup._cli_tools._is_macos", return_value=True)
    @patch("services.setup._cli_tools._ensure_macports", return_value=False)
    @patch("services.setup._cli_tools._has_brew", return_value=True)
    @patch("subprocess.run")
    def test_node_install_macos_falls_back_to_brew(self, mock_run, mock_brew, mock_mp, mock_macos, console):
        """On macOS, if MacPorts fails/missing, use Homebrew."""
        mock_run.return_value = MagicMock(returncode=0)
        check = NodeCheck()
        assert check.install(console) is True
        mock_run.assert_called_with(["brew", "install", "node"], check=True, text=True)
