def configure_board(env):
    framework = env.get("PIOFRAMEWORK", [])

    if "arduino" in framework:
        arduino_deps = [
            "https://github.com/M5Stack/M5Unified.git",
            "https://github.com/M5Stack/M5GFX.git"
        ]

        env.AppendUnique(LIB_DEPS=arduino_deps)
        print("M5stack ESP32-P4 Tab5: Added Arduino dependencies")
