def configure_board(env):
    framework = env.get("PIOFRAMEWORK", [])

    if "arduino" in framework:
        m5tab_deps = [
            "https://github.com/M5Stack/M5Unified.git",
            "https://github.com/M5Stack/M5GFX.git"
        ]
        
        # Install libraries using PlatformIO CLI
        try:
            import subprocess
            from pathlib import Path
            pioenv = env.subst("$PIOENV")
            project_dir = env.subst("$PROJECT_DIR")

            for lib in m5tab_deps:
                lib_name = lib.split("/")[-1].replace(".git", "")
                lib_path = Path(project_dir) / ".pio" / "libdeps" / pioenv
                print(f"M5stack ESP32-P4 Tab5: Installing library '{lib_name}' at '{lib_path}'")
                try:
                    result = subprocess.run(
                        ["platformio", "lib", "-e", pioenv, "-d", lib_path, "install", lib_name],
                        capture_output=True, 
                        text=True,
#                        cwd=project_dir,
                        timeout=60
                    )
                    
                    if result.returncode == 0:
                        print(f"M5stack ESP32-P4 Tab5: Successfully installed {lib_name}")
                    else:
                        print(f"M5stack ESP32-P4 Tab5: Failed to install {lib_name}: {result.stderr}")
                        
                except subprocess.TimeoutExpired:
                    print(f"M5stack ESP32-P4 Tab5: Timeout installing {lib_name}")
                except Exception as e:
                    print(f"M5stack ESP32-P4 Tab5: Error installing {lib_name}: {e}")
                    
        except Exception as e:
            print(f"M5stack ESP32-P4 Tab5: Library installation error: {e}")
