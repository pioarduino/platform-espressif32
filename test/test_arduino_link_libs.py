import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "builder" / "frameworks"))
from arduino_link_libs import configure_arduino_link_libs


class FakeEnvironment(dict):
    def __init__(self, libraries, dependencies):
        super().__init__(LIBS=libraries)
        self.dependencies = dependencies
        self.processed = False

    def ProcessProjectDeps(self):
        self.processed = True

    def GetLibBuilders(self):
        return self.dependencies

    def Replace(self, **kwargs):
        self.update(kwargs)

    def AddMethod(self, function, name):
        setattr(self, name, function.__get__(self))


class TestArduinoLinkLibs(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.framework = Path(self.temporary.name)
        self.matter_path = self.framework / "libraries" / "Matter"
        self.archive = (
            self.framework / "tools" / "esp32-arduino-libs" / "esp32c3"
            / "lib" / "libbt.matter.a"
        )

    def configure(self, dependent=True, library_path=None, archive=True):
        if archive:
            self.archive.parent.mkdir(parents=True, exist_ok=True)
            self.archive.touch()
        library = SimpleNamespace(
            is_dependent=dependent, path=library_path or self.matter_path
        )
        env = FakeEnvironment(
            ["-lbt", "-lbtdm_app", "-lbt", "bt", "btbb"], [library]
        )
        configure_arduino_link_libs(env, self.framework, "esp32c3")
        env.ProcessProjectDeps()
        self.assertTrue(env.processed)
        return env["LIBS"]

    def test_selects_matter_archive_for_discovered_framework_library(self):
        self.assertEqual(
            self.configure(),
            ["-lbt.matter", "-lbtdm_app", "-lbt.matter", "bt.matter", "btbb"],
        )

    def test_preserves_normal_archive_without_matter_dependency(self):
        self.assertEqual(self.configure(dependent=False)[0], "-lbt")

    def test_preserves_normal_archive_without_matter_bt_archive(self):
        self.assertEqual(self.configure(archive=False)[0], "-lbt")

    def test_ignores_other_libraries_named_matter(self):
        self.assertEqual(self.configure(library_path=self.framework / "other" / "Matter")[0], "-lbt")

    def test_selects_libraries_added_during_dependency_processing(self):
        self.archive.parent.mkdir(parents=True)
        self.archive.touch()
        library = SimpleNamespace(is_dependent=False, path=self.matter_path)
        env = FakeEnvironment([], [library])

        def discover_dependencies():
            library.is_dependent = True
            env["LIBS"].extend(["-lbt", "-lbt"])

        env.ProcessProjectDeps = discover_dependencies
        configure_arduino_link_libs(env, self.framework, "esp32c3")
        env.ProcessProjectDeps()
        self.assertEqual(env["LIBS"], ["-lbt.matter", "-lbt.matter"])


if __name__ == "__main__":
    unittest.main()
