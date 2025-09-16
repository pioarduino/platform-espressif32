def configure_board(env):
    if "arduino" in env.get("PIOFRAMEWORK", []):
        m5tab_deps = ["https://github.com/M5Stack/M5Unified.git"]
        # Install libraries using PlatformIO Library Manager
        from pathlib import Path
        from platformio.package.manager.library import LibraryPackageManager

        lib_dir = Path(env.subst("$PROJECT_DIR")) / ".pio" / "libdeps" / env.subst("$PIOENV")
        lm = LibraryPackageManager(package_dir=lib_dir)

        for lib in m5tab_deps:
            lm.install(lib)
