#!/usr/bin/env python3
"""
Regression tests for the toolchain-wipe fix in platform.py.

Covers two scenarios in Espressif32Platform.install_tool() /
_handle_existing_tool():

1. A version mismatch must actually trigger a reinstall (the tool is not
   left as a bare registry stub after install_tool() returns True).
2. Calling install_tool() twice for the same tool within one platform
   instance's lifetime must not lose the original platform.json source.
   The version-match branch repoints self.packages[tool_name]["version"]
   at a local path; without caching the original source on first sight,
   a later mismatch for that same tool reads the local path instead of a
   real URL and silently skips reinstalling it (github.com/pioarduino/
   platform-espressif32/pull/527).
"""

import importlib.util
import os
import sys
import sysconfig
import unittest
from unittest import mock


def _load_real_stdlib_platform_module():
    # The repo root (which contains a file literally named platform.py) ends
    # up on sys.path when tests run via `python -m unittest`, ahead of the
    # real standard library directory. A plain `import platform` here would
    # therefore be order-dependent - it only resolves correctly if something
    # else already imported the real module first. Load it deterministically
    # by its known path instead, bypassing sys.path search entirely, so
    # anything that later does `import platform` (e.g. pyserial's miniterm,
    # imported transitively through platformio.public) gets the genuine
    # standard library module regardless of import order.
    stdlib_path = os.path.join(sysconfig.get_path("stdlib"), "platform.py")
    spec = importlib.util.spec_from_file_location("platform", stdlib_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["platform"] = module
    spec.loader.exec_module(module)
    return module


_load_real_stdlib_platform_module()

PLATFORM_PY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "platform.py")


def load_platform_module():
    # platform.py shares its name with the stdlib "platform" module, so it's
    # loaded under a distinct module name rather than via a plain import -
    # the same approach platformio.platform.factory.PlatformFactory uses.
    spec = importlib.util.spec_from_file_location("espressif32_platform_under_test", PLATFORM_PY)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ToolReinstallTestCase(unittest.TestCase):
    """Base fixture: a bare Espressif32Platform instance with mocked collaborators."""

    def setUp(self):
        self.platform_module = load_platform_module()

        # PlatformBase.__init__ needs a real platform.json + ProjectConfig,
        # which this test has no interest in exercising - bypass it and set
        # up just the state install_tool()/_handle_existing_tool() touch.
        self.platform = object.__new__(self.platform_module.Espressif32Platform)
        self.platform._packages_dir = "/fake/packages"
        self.platform._tools_cache = {}
        self.platform._mcu_config_cache = {}
        self.platform._tool_sources = {}
        self.platform._penv_python = None
        self.platform._manifest = {
            "packages": {
                "toolchain-xtensa-esp-elf": {
                    "type": "toolchain",
                    "optional": True,
                    "owner": "pioarduino",
                    "package-version": "14.2.0+20260121",
                    "version": "https://github.com/pioarduino/registry/releases/download/0.0.1/xtensa-esp-elf-14.2.0_20260121.zip",
                }
            }
        }
        self.platform._custom_packages = None

        self.pm_install_patcher = mock.patch.object(self.platform_module, "pm")
        self.mock_pm = self.pm_install_patcher.start()
        self.addCleanup(self.pm_install_patcher.stop)

        self.remove_dir_patcher = mock.patch.object(self.platform_module, "safe_remove_directory")
        self.mock_remove_dir = self.remove_dir_patcher.start()
        self.addCleanup(self.remove_dir_patcher.stop)

        paths_patcher = mock.patch.object(
            self.platform_module.Espressif32Platform, "_get_tool_paths",
            return_value={
                "tool_path": "/fake/packages/toolchain-xtensa-esp-elf",
                "tools_json_path": "/fake/packages/toolchain-xtensa-esp-elf/tools.json",
                "idf_tools_path": "/fake/tools/idf_tools.py",
                "package_path": "/fake/packages/toolchain-xtensa-esp-elf/package.json",
            },
        )
        paths_patcher.start()
        self.addCleanup(paths_patcher.stop)

    def set_tool_status(self, **overrides):
        status = {
            "has_idf_tools": True,
            "has_tools_json": False,
            "has_piopm": True,
            "tool_exists": True,
        }
        status.update(overrides)
        patcher = mock.patch.object(
            self.platform_module.Espressif32Platform, "_check_tool_status", return_value=status
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def set_version_check(self, matches):
        patcher = mock.patch.object(
            self.platform_module.Espressif32Platform, "_check_tool_version", return_value=matches
        )
        patcher.start()
        self.addCleanup(patcher.stop)


class TestMismatchTriggersReinstall(ToolReinstallTestCase):
    """A version mismatch must re-fetch the real source, not fall through silently."""

    def test_mismatch_refetches_https_source_before_recursing(self):
        self.set_tool_status()
        self.set_version_check(matches=False)
        # Populate the cache the way a real install_tool() call would,
        # without going through install_tool() itself - the routing between
        # Case 1/Case 2/fall-through in install_tool() is not what this
        # test is exercising, only _handle_existing_tool()'s mismatch branch.
        self.platform._tool_sources["toolchain-xtensa-esp-elf"] = (
            self.platform.packages["toolchain-xtensa-esp-elf"]["version"]
        )
        paths = self.platform_module.Espressif32Platform._get_tool_paths(
            self.platform, "toolchain-xtensa-esp-elf"
        )

        # install_tool()'s own recursive call at the end of
        # _handle_existing_tool() (after the re-fetch) is not under test
        # here - stub it so this test stays focused on whether the re-fetch
        # itself happens, with the right source, before that recursion.
        with mock.patch.object(
            self.platform_module.Espressif32Platform, "install_tool", return_value=True
        ):
            result = self.platform_module.Espressif32Platform._handle_existing_tool(
                self.platform, "toolchain-xtensa-esp-elf", paths
            )

        self.assertTrue(result)
        self.mock_pm.install.assert_called_once_with(
            "https://github.com/pioarduino/registry/releases/download/0.0.1/xtensa-esp-elf-14.2.0_20260121.zip"
        )
        self.mock_remove_dir.assert_called_once_with("/fake/packages/toolchain-xtensa-esp-elf")


class TestSecondMismatchAfterEarlierMatch(ToolReinstallTestCase):
    """
    Reproduces the scenario from the PR #527 review comment: a package that
    is install_tool()'d twice in one platform instance's lifetime (e.g.
    required by both _configure_mcu_toolchains() and
    _configure_rom_elfs_for_exception_decoder() for tool-esp-rom-elfs) must
    not lose its real source on the second call just because the first call
    took the version-match branch and repointed "version" at a local path.
    """

    def test_original_source_survives_an_intervening_match(self):
        self.set_tool_status()

        original_source = self.platform.packages["toolchain-xtensa-esp-elf"]["version"]

        # First call: version matches. This mutates
        # self.packages[tool_name]["version"] to a local path, per the
        # existing (unmodified) behavior in _handle_existing_tool().
        self.set_version_check(matches=True)
        first_result = self.platform_module.Espressif32Platform.install_tool(
            self.platform, "toolchain-xtensa-esp-elf"
        )
        self.assertTrue(first_result)
        self.assertNotEqual(
            self.platform.packages["toolchain-xtensa-esp-elf"]["version"], original_source
        )

        # Second call, same instance: version now mismatches (e.g. the
        # install got corrupted between checks). The recovery path must
        # still re-fetch the *original* https:// source, not the local
        # path the first call left behind.
        self.set_version_check(matches=False)
        with mock.patch.object(
            self.platform_module.Espressif32Platform, "install_tool",
            side_effect=[None, True],
        ):
            self.platform_module.Espressif32Platform._handle_existing_tool(
                self.platform,
                "toolchain-xtensa-esp-elf",
                self.platform_module.Espressif32Platform._get_tool_paths(self.platform, "toolchain-xtensa-esp-elf"),
            )

        self.mock_pm.install.assert_called_once_with(original_source)


if __name__ == "__main__":
    unittest.main()
