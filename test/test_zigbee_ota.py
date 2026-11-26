import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "builder" / "frameworks"))
from zigbee_ota import create_zigbee_ota_image


class FakeEnvironment(dict):
    def __init__(self, framework, root, defines):
        super().__init__(CPPDEFINES=defines)
        self.framework = framework
        self.paths = {
            "$PYTHONEXE": sys.executable,
            "$PROJECT_SRC_DIR": str(root / "src"),
            "$BUILD_DIR": str(root / "build"),
        }

    def PioPlatform(self):
        return SimpleNamespace(get_package_dir=lambda name: str(self.framework))

    def subst(self, value):
        return self.paths[value]


class TestZigbeeOta(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="zigbee ota ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.framework = self.root / "framework"
        self.script = self.framework / "tools" / "zb_ota_image.py"
        self.script.parent.mkdir(parents=True)
        self.script.touch()
        self.binary = self.root / "build" / "firmware.bin"

    @patch("zigbee_ota.subprocess.run")
    def test_runs_generator_for_both_modes(self, run):
        run.return_value.returncode = 0
        for define, mode in [
            ("ZIGBEE_MODE_ED", "ZIGBEE_MODE_ED"),
            (("ZIGBEE_MODE_ZCZR", 1), "ZIGBEE_MODE_ZCZR"),
        ]:
            with self.subTest(mode=mode):
                env = FakeEnvironment(self.framework, self.root, [define])
                create_zigbee_ota_image([], [self.binary], env)
                run.assert_called_once_with([
                    sys.executable, str(self.script), f"--zigbee-mode=-D{mode}",
                    "--sketch", str(self.root / "src"),
                    "--bin", str(self.binary), "--build-path", str(self.root / "build"),
                ], check=False)
                run.reset_mock()

    @patch("zigbee_ota.subprocess.run")
    def test_skips_when_zigbee_is_disabled(self, run):
        env = FakeEnvironment(self.framework, self.root, ["UNRELATED_DEFINE"])
        create_zigbee_ota_image([], [self.binary], env)
        run.assert_not_called()

    @patch("zigbee_ota.subprocess.run")
    def test_missing_generator_does_not_fail_build(self, run):
        self.script.unlink()
        env = FakeEnvironment(self.framework, self.root, {"ZIGBEE_MODE_ED": 1})
        create_zigbee_ota_image([], [self.binary], env)
        run.assert_not_called()

    @patch("zigbee_ota.subprocess.run", side_effect=OSError("failed"))
    def test_generator_start_failure_does_not_fail_build(self, run):
        env = FakeEnvironment(self.framework, self.root, ["ZIGBEE_MODE_ED"])
        self.assertIsNone(create_zigbee_ota_image([], [self.binary], env))

    @patch("zigbee_ota.subprocess.run")
    def test_generator_failure_does_not_fail_build(self, run):
        run.return_value.returncode = 1
        env = FakeEnvironment(self.framework, self.root, {"ZIGBEE_MODE_ED": 1})
        self.assertIsNone(create_zigbee_ota_image([], [self.binary], env))
        run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
