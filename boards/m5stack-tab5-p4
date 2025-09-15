def configure_board(env):
    framework = env.get("PIOFRAMEWORK", [])

    if "arduino" in framework:
        arduino_deps = [
            "https://github.com/M5Stack/M5Unified.git",
            "https://github.com/M5Stack/M5GFX.git"
        ]

        current_deps = env.GetProjectOption("lib_deps", [])
        if isinstance(current_deps, str):
            current_deps = [current_deps]
        elif current_deps is None:
            current_deps = []

        for dep in arduino_deps:
            if dep not in current_deps:
                current_deps.append(dep)
  
        env.Replace(LIB_DEPS=current_deps)
        print("M5stack ESP32-P4 Tab5: Added Arduino dependencies")
