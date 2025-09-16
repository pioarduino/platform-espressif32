def configure_board(env):
    framework = env.get("PIOFRAMEWORK", [])

    if "arduino" in framework:
        m5tab_deps = ["https://github.com/M5Stack/M5Unified.git"]

        # Install libraries using PlatformIO Library Manager
        try:
            from pathlib import Path
            from platformio.package.manager.library import LibraryPackageManager
            
            pioenv = env.subst("$PIOENV")
            lib_dir = Path(env.subst("$PROJECT_DIR")) / ".pio" / "libdeps" / pioenv
            lm = LibraryPackageManager(package_dir=lib_dir)

            for lib in m5tab_deps:
                lib_name = lib.split("/")[-1].replace(".git", "")
                lib_path = Path(lib_dir) / lib_name
                
                # Skip if already installed
                if lib_path.exists():
                    continue

                try:
                    result = lm.install(lib)
                    
                    if result.returncode == 0:
                        print(f"M5stack ESP32-P4 Tab5: Successfully installed {lib_name}")
                    else:
                        print(f"M5stack ESP32-P4 Tab5: Failed to install {lib_name}: {result.stderr}")

                except Exception as e:
                    print(f"M5stack ESP32-P4 Tab5: Error installing {lib_name}: {e}")
                    
        except Exception as e:
            print(f"M5stack ESP32-P4 Tab5: Library installation error: {e}")
