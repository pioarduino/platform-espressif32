import subprocess
import sys
from pathlib import Path


def create_zigbee_ota_image(source, target, env):
    defines = env.get("CPPDEFINES", [])
    if isinstance(defines, str):
        defines = defines.split()
    elif isinstance(defines, (dict, tuple)):
        defines = [defines]

    names = set()
    for define in defines:
        if isinstance(define, dict):
            names.update(str(name).split("=", 1)[0] for name in define)
        elif isinstance(define, (tuple, list)):
            if define:
                names.add(str(define[0]).split("=", 1)[0])
        elif define is not None:
            names.add(str(define).split("=", 1)[0])
    mode = next((name for name in ("ZIGBEE_MODE_ED", "ZIGBEE_MODE_ZCZR") if name in names), None)
    if not mode:
        return

    framework_dir = env.PioPlatform().get_package_dir("framework-arduinoespressif32")
    script = Path(framework_dir) / "tools" / "zb_ota_image.py" if framework_dir else None
    if not script or not script.is_file():
        print("Warning: Zigbee OTA image generator is not available in the Arduino framework")
        return

    command = [
        env.subst("$PYTHONEXE") or sys.executable,
        str(script),
        f"--zigbee-mode=-D{mode}",
        "--sketch", env.subst("$PROJECT_SRC_DIR"),
        "--bin", str(target[0]),
        "--build-path", env.subst("$BUILD_DIR"),
    ]
    try:
        result = subprocess.run(command, check=False)
        if result.returncode:
            print(f"Warning: Zigbee OTA image generator exited with code {result.returncode}")
    except OSError as error:
        print(f"Warning: could not run Zigbee OTA image generator: {error}")
