import ast
import unittest
from pathlib import Path
from unittest.mock import Mock


class TestArduinoBluetoothLinkFlags(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parent.parent / "builder/frameworks/arduino.py"
        module = ast.parse(path.read_text(encoding="utf8"), filename=str(path))
        for outer in module.body:
            if not isinstance(outer, ast.If):
                continue
            for inner in outer.body:
                if isinstance(inner, ast.If) and any(
                    isinstance(node, ast.Constant)
                    and node.value == "-Wl,--wrap=esp_bt_mem_release"
                    for node in ast.walk(inner)
                ):
                    isolated = ast.Module(
                        body=[ast.If(test=outer.test, body=[inner], orelse=[])],
                        type_ignores=[],
                    )
                    cls.code = compile(ast.fix_missing_locations(isolated), str(path), "exec")
                    return
        raise AssertionError("Arduino Bluetooth linker flag condition not found")

    def check_flags(self, framework, compile_flag, custom_sdkconfig=False, board=None):
        env = Mock()
        config = Mock()
        config.has_option.return_value = custom_sdkconfig
        exec(self.code, {
            "pioframework": framework,
            "arduino_lib_compile_flag": compile_flag,
            "config": config,
            "current_env_section": "env:test",
            "board": board or {},
            "env": env,
        })
        return env.AppendUnique

    def test_normal_arduino_build_adds_flags(self):
        self.check_flags("arduino", "Inactive").assert_called_once_with(LINKFLAGS=[
            "-Wl,--wrap=esp_bt_mem_release",
            "-Wl,--wrap=esp_bt_controller_mem_release",
        ])

    def test_other_build_modes_do_not_add_flags(self):
        cases = [
            ("espidf", "Inactive", False, {}),
            ("arduino espidf", "Inactive", False, {}),
            ("arduino", "Build", True, {}),
            ("arduino", "True", True, {}),
            ("arduino", "Inactive", True, {}),
            ("arduino", "Inactive", False, {"espidf.custom_sdkconfig": ""}),
        ]
        for framework, flag, custom_sdkconfig, board in cases:
            with self.subTest(framework=framework, flag=flag, custom=custom_sdkconfig, board=board):
                self.check_flags(framework, flag, custom_sdkconfig, board).assert_not_called()


if __name__ == "__main__":
    unittest.main()
