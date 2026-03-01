"""
Unit tests for builder/penv_setup.py

Tests Python environment setup, dependency management, and esptool installation.
"""
import os
import sys
import unittest
from unittest.mock import Mock, MagicMock, patch, call
from pathlib import Path
import json
import socket
import subprocess

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "builder"))

# Mock platformio modules
sys.modules['platformio'] = MagicMock()
sys.modules['platformio.package'] = MagicMock()
sys.modules['platformio.package.version'] = MagicMock()
sys.modules['platformio.compat'] = MagicMock()

import penv_setup


class TestInternetConnection(unittest.TestCase):
    """Test has_internet_connection function."""

    def test_internet_with_proxy(self):
        """Test internet check with HTTPS proxy."""
        with patch.dict(os.environ, {'HTTPS_PROXY': 'http://proxy.example.com:8080'}):
            with patch('socket.create_connection') as mock_socket:
                mock_socket.return_value.close = MagicMock()
                result = penv_setup.has_internet_connection(timeout=1)
                self.assertTrue(result)
                mock_socket.assert_called_once()

    def test_internet_proxy_failed(self):
        """Test internet check when proxy connection fails."""
        with patch.dict(os.environ, {'HTTPS_PROXY': 'http://proxy.example.com:8080'}):
            with patch('socket.create_connection') as mock_socket:
                mock_socket.side_effect = OSError("Connection failed")
                # Should fall back to direct connection
                result = penv_setup.has_internet_connection(timeout=1)
                # Will fail in both proxy and direct
                self.assertFalse(result)

    def test_internet_direct_connection(self):
        """Test internet check with direct connection."""
        with patch.dict(os.environ, {}, clear=True):
            with patch('socket.create_connection') as mock_socket:
                mock_socket.return_value.close = MagicMock()
                result = penv_setup.has_internet_connection(timeout=1)
                self.assertTrue(result)

    def test_internet_no_connection(self):
        """Test internet check when no connection available."""
        with patch.dict(os.environ, {}, clear=True):
            with patch('socket.create_connection') as mock_socket:
                mock_socket.side_effect = OSError("No connection")
                result = penv_setup.has_internet_connection(timeout=1)
                self.assertFalse(result)


class TestGetExecutablePath(unittest.TestCase):
    """Test get_executable_path function."""

    def test_executable_path_windows(self):
        """Test getting executable path on Windows."""
        with patch('penv_setup.IS_WINDOWS', True):
            result = penv_setup.get_executable_path("/path/to/penv", "python")
            expected = str(Path("/path/to/penv") / "Scripts" / "python.exe")
            self.assertEqual(result, expected)

    def test_executable_path_unix(self):
        """Test getting executable path on Unix."""
        with patch('penv_setup.IS_WINDOWS', False):
            result = penv_setup.get_executable_path("/path/to/penv", "python")
            expected = str(Path("/path/to/penv") / "bin" / "python")
            self.assertEqual(result, expected)

    def test_executable_path_tool_windows(self):
        """Test getting tool executable path on Windows."""
        with patch('penv_setup.IS_WINDOWS', True):
            result = penv_setup.get_executable_path("/path/to/penv", "esptool")
            expected = str(Path("/path/to/penv") / "Scripts" / "esptool.exe")
            self.assertEqual(result, expected)


class TestSetupPipenvInPackage(unittest.TestCase):
    """Test setup_pipenv_in_package function."""

    def setUp(self):
        """Set up test environment."""
        self.mock_env = MagicMock()
        self.mock_env.subst.return_value = sys.executable
        self.penv_dir = "/tmp/test_penv"

    def test_setup_with_uv(self):
        """Test setting up virtual environment with uv."""
        with patch('os.path.isfile') as mock_isfile:
            mock_isfile.side_effect = [False, True, True]  # No python, then uv found, then python exists
            with patch('subprocess.check_call') as mock_subprocess:
                with patch('penv_setup.IS_WINDOWS', False):
                    result = penv_setup.setup_pipenv_in_package(self.mock_env, self.penv_dir)
                    self.assertIsNotNone(result)
                    mock_subprocess.assert_called_once()

    def test_setup_fallback_venv(self):
        """Test falling back to python -m venv."""
        with patch('os.path.isfile') as mock_isfile:
            mock_isfile.side_effect = [False, False, True]  # No python initially, no uv, then python exists
            with patch('subprocess.check_call') as mock_subprocess:
                mock_subprocess.side_effect = [Exception("uv failed"), None]  # First call (uv) fails
                result = penv_setup.setup_pipenv_in_package(self.mock_env, self.penv_dir)
                self.assertIsNone(result)

    def test_setup_already_exists(self):
        """Test when virtual environment already exists."""
        with patch('os.path.isfile') as mock_isfile:
            mock_isfile.return_value = True
            result = penv_setup.setup_pipenv_in_package(self.mock_env, self.penv_dir)
            self.assertIsNone(result)


class TestGetPackagesToInstall(unittest.TestCase):
    """Test get_packages_to_install function."""

    def test_package_not_installed(self):
        """Test when package is not installed."""
        deps = {"littlefs-python": ">=0.16.0"}
        installed = {}
        result = list(penv_setup.get_packages_to_install(deps, installed))
        self.assertEqual(result, ["littlefs-python"])

    def test_package_already_installed(self):
        """Test when package is already installed with correct version."""
        with patch('penv_setup.semantic_version.SimpleSpec') as mock_spec:
            mock_spec_instance = MagicMock()
            mock_spec_instance.match.return_value = True
            mock_spec.return_value = mock_spec_instance

            deps = {"littlefs-python": ">=0.16.0"}
            installed = {"littlefs-python": "0.16.1"}
            result = list(penv_setup.get_packages_to_install(deps, installed))
            self.assertEqual(result, [])

    def test_package_version_mismatch(self):
        """Test when installed package version doesn't match."""
        with patch('penv_setup.semantic_version.SimpleSpec') as mock_spec:
            mock_spec_instance = MagicMock()
            mock_spec_instance.match.return_value = False
            mock_spec.return_value = mock_spec_instance

            deps = {"littlefs-python": ">=0.16.0"}
            installed = {"littlefs-python": "0.15.0"}
            result = list(penv_setup.get_packages_to_install(deps, installed))
            self.assertEqual(result, ["littlefs-python"])

    def test_platformio_version_check(self):
        """Test special handling for platformio version."""
        with patch('penv_setup.pepver_to_semver') as mock_pepver:
            mock_pepver.return_value = "6.1.19"

            deps = {
                "platformio": "https://github.com/pioarduino/platformio-core/archive/refs/tags/v6.1.19.zip"
            }
            installed = {"platformio": "6.1.19"}
            result = list(penv_setup.get_packages_to_install(deps, installed))
            self.assertEqual(result, [])

    def test_platformio_version_mismatch(self):
        """Test platformio reinstall on version mismatch."""
        with patch('penv_setup.pepver_to_semver') as mock_pepver:
            mock_pepver.return_value = "6.1.19"

            deps = {
                "platformio": "https://github.com/pioarduino/platformio-core/archive/refs/tags/v6.1.19.zip"
            }
            installed = {"platformio": "6.1.18"}
            result = list(penv_setup.get_packages_to_install(deps, installed))
            self.assertEqual(result, ["platformio"])


class TestInstallPythonDeps(unittest.TestCase):
    """Test install_python_deps function."""

    def setUp(self):
        """Set up test environment."""
        self.python_exe = "/tmp/penv/bin/python"
        self.uv_executable = "/tmp/uv"

    def test_install_deps_success(self):
        """Test successful dependency installation."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0)
            with patch('subprocess.check_call') as mock_check_call:
                result = penv_setup.install_python_deps(
                    self.python_exe, self.uv_executable
                )
                self.assertTrue(result)

    def test_install_deps_with_cache(self):
        """Test dependency installation with cache directory."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0)
            with patch('subprocess.check_call') as mock_check_call:
                result = penv_setup.install_python_deps(
                    self.python_exe, self.uv_executable, uv_cache_dir="/tmp/cache"
                )
                self.assertTrue(result)

    def test_install_deps_failure(self):
        """Test handling of installation failure."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0)
            with patch('subprocess.check_call') as mock_check_call:
                mock_check_call.side_effect = subprocess.CalledProcessError(1, "uv")
                result = penv_setup.install_python_deps(
                    self.python_exe, self.uv_executable
                )
                self.assertFalse(result)

    def test_install_deps_timeout(self):
        """Test handling of installation timeout."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0)
            with patch('subprocess.check_call') as mock_check_call:
                mock_check_call.side_effect = subprocess.TimeoutExpired("uv", 300)
                result = penv_setup.install_python_deps(
                    self.python_exe, self.uv_executable
                )
                self.assertFalse(result)


class TestInstallEsptool(unittest.TestCase):
    """Test install_esptool function."""

    def setUp(self):
        """Set up test environment."""
        self.mock_env = MagicMock()
        self.mock_platform = MagicMock()
        self.mock_platform.get_package_dir.return_value = "/tmp/tool-esptoolpy"
        self.python_exe = "/tmp/penv/bin/python"
        self.uv_executable = "/tmp/penv/bin/uv"

    def test_install_esptool_success(self):
        """Test successful esptool installation."""
        with patch('os.path.isdir') as mock_isdir:
            mock_isdir.return_value = True
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = Mock(returncode=1, stdout="MISMATCH")
                with patch('subprocess.check_call') as mock_check_call:
                    penv_setup.install_esptool(
                        self.mock_env, self.mock_platform,
                        self.python_exe, self.uv_executable
                    )
                    mock_check_call.assert_called_once()

    def test_install_esptool_already_installed(self):
        """Test when esptool is already correctly installed."""
        with patch('os.path.isdir') as mock_isdir:
            mock_isdir.return_value = True
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = Mock(returncode=0, stdout="MATCH")
                with patch('subprocess.check_call') as mock_check_call:
                    penv_setup.install_esptool(
                        self.mock_env, self.mock_platform,
                        self.python_exe, self.uv_executable
                    )
                    mock_check_call.assert_not_called()

    def test_install_esptool_missing_package(self):
        """Test error when tool-esptoolpy package is missing."""
        self.mock_platform.get_package_dir.return_value = ""
        with self.assertRaises(SystemExit):
            penv_setup.install_esptool(
                self.mock_env, self.mock_platform,
                self.python_exe, self.uv_executable
            )

    def test_install_esptool_installation_failure(self):
        """Test handling of esptool installation failure."""
        with patch('os.path.isdir') as mock_isdir:
            mock_isdir.return_value = True
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = Mock(returncode=1, stdout="MISMATCH")
                with patch('subprocess.check_call') as mock_check_call:
                    mock_check_call.side_effect = subprocess.CalledProcessError(1, "uv")
                    with self.assertRaises(SystemExit):
                        penv_setup.install_esptool(
                            self.mock_env, self.mock_platform,
                            self.python_exe, self.uv_executable
                        )


class TestSetupPythonPaths(unittest.TestCase):
    """Test setup_python_paths function."""

    def test_setup_paths_windows(self):
        """Test setting up Python paths on Windows."""
        with patch('penv_setup.IS_WINDOWS', True):
            with patch('os.path.isdir') as mock_isdir:
                mock_isdir.return_value = True
                with patch('site.addsitedir') as mock_add:
                    penv_setup.setup_python_paths("/tmp/penv")
                    mock_add.assert_called_once()

    def test_setup_paths_unix(self):
        """Test setting up Python paths on Unix."""
        with patch('penv_setup.IS_WINDOWS', False):
            with patch('os.path.isdir') as mock_isdir:
                mock_isdir.return_value = True
                with patch('site.addsitedir') as mock_add:
                    penv_setup.setup_python_paths("/tmp/penv")
                    mock_add.assert_called_once()

    def test_setup_paths_missing_dir(self):
        """Test handling when site-packages directory doesn't exist."""
        with patch('os.path.isdir') as mock_isdir:
            mock_isdir.return_value = False
            with patch('site.addsitedir') as mock_add:
                penv_setup.setup_python_paths("/tmp/penv")
                mock_add.assert_not_called()


class TestSetupCertifiEnv(unittest.TestCase):
    """Test _setup_certifi_env function."""

    def test_setup_certifi_success(self):
        """Test setting up certifi environment variables."""
        mock_env = MagicMock()
        python_exe = "/tmp/penv/bin/python"

        with patch('subprocess.check_output') as mock_output:
            mock_output.return_value = "/tmp/penv/lib/python3.10/site-packages/certifi/cacert.pem\n"

            with patch.dict(os.environ, {}, clear=True):
                penv_setup._setup_certifi_env(mock_env, python_exe)

                self.assertEqual(os.environ['CERTIFI_PATH'],
                    "/tmp/penv/lib/python3.10/site-packages/certifi/cacert.pem")
                self.assertEqual(os.environ['SSL_CERT_FILE'],
                    "/tmp/penv/lib/python3.10/site-packages/certifi/cacert.pem")

    def test_setup_certifi_failure(self):
        """Test handling of certifi setup failure."""
        mock_env = MagicMock()
        python_exe = "/tmp/penv/bin/python"

        with patch('subprocess.check_output') as mock_output:
            mock_output.side_effect = Exception("Failed to get certifi")

            # Should not raise exception
            penv_setup._setup_certifi_env(mock_env, python_exe)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def test_empty_package_dict(self):
        """Test get_packages_to_install with empty package dict."""
        result = list(penv_setup.get_packages_to_install({}, {}))
        self.assertEqual(result, [])

    def test_malformed_version_string(self):
        """Test handling of malformed version strings."""
        with patch('penv_setup.semantic_version.SimpleSpec') as mock_spec:
            mock_spec.side_effect = ValueError("Invalid version")

            deps = {"package": "invalid_version"}
            installed = {"package": "1.0.0"}

            # Should handle the exception gracefully
            try:
                result = list(penv_setup.get_packages_to_install(deps, installed))
            except ValueError:
                self.fail("Should handle ValueError gracefully")


if __name__ == '__main__':
    unittest.main()