from pathlib import Path


def configure_arduino_link_libs(env, framework_dir, chip_variant):
    matter_library = Path(framework_dir, "libraries", "Matter").resolve()
    matter_bt = Path(
        framework_dir, "tools", "esp32-arduino-libs", chip_variant,
        "lib", "libbt.matter.a"
    )
    process_project_deps = env.ProcessProjectDeps

    def process_deps_and_select_bt(build_env):
        process_project_deps()
        if not matter_bt.is_file():
            return
        if not any(
            library.is_dependent and Path(library.path).resolve() == matter_library
            for library in build_env.GetLibBuilders()
        ):
            return
        build_env.Replace(LIBS=[
            {"-lbt": "-lbt.matter", "bt": "bt.matter"}.get(lib, lib)
            if isinstance(lib, str) else lib
            for lib in build_env.get("LIBS", [])
        ])

    env.AddMethod(process_deps_and_select_bt, "ProcessProjectDeps")
