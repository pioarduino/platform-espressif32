"""
Board memory fingerprint for the Arduino HybridCompile checksum.

The PSRAM settings that end up in the generated sdkconfig are taken from the
board manifest and are not part of "custom_sdkconfig". They therefore have to
be folded into the checksum, otherwise a board with PSRAM and a board without
it that share the same "custom_sdkconfig" reuse each other's precompiled
Arduino libs. This module is used by both the comparison path (arduino.py) and
the generation path (espidf.py) so that the two always agree.
"""

from platformio.exception import PlatformioException


def _project_option(env, name):
    """Value of an optional project option, empty string when it is not set.

    A failed lookup is reported rather than silently dropped, because omitting
    an active override would make two different configurations share libs.
    """
    try:
        return env.GetProjectOption(name, "") or ""
    except PlatformioException as exc:
        print(f"Warning: cannot read {name} for the Arduino libs checksum: {exc}")
        return ""


def board_memory_fingerprint(env, board):
    """PSRAM/memory settings of the board, as a string for the checksum."""
    extra_flags = board.get("build.extra_flags", [])
    if not isinstance(extra_flags, str):
        extra_flags = " ".join(str(flag) for flag in extra_flags)

    build_section = board.get("build", {})
    memory_type = (_project_option(env, "board_build.memory_type")
                   or build_section.get("arduino", {}).get("memory_type", "")
                   or build_section.get("memory_type", ""))
    psram_type = (_project_option(env, "board_build.psram_type")
                  or build_section.get("psram_type", ""))

    return f"|{'PSRAM' in extra_flags}|{memory_type}|{psram_type}"
