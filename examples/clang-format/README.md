# clang-format example

This example shows how to format an Arduino project with the `clangformat` and
`clangformat-write` targets of pioarduino / platform-espressif32, and how to
enforce the formatting in CI.

## Project layout

```
examples/clang-format/
├── .clang-format     # clang-format style used by this project
├── platformio.ini    # project configuration (custom_clang_format = check)
└── src/
    └── main.cpp      # already formatted source file
```

## Usage

The clang-format tool is installed automatically the first time one of the
targets runs — no separate installation step is needed.

```shell
# Change directory to the example
cd platform-espressif32/examples/clang-format

# Check the formatting without modifying any file (what CI runs)
pio run -t clangformat

# Format all scanned source files in-place
pio run -t clangformat-write
```

The `clangformat` target runs clang-format in dry-run mode and exits with a
non-zero status as soon as a file is not correctly formatted, which is what
makes it usable as a CI gate. `clangformat-write` formats the files in-place
and exits with a non-zero status only on real errors.

## Configuration

All options are set in `platformio.ini`:

| Option | Default | Description |
| --- | --- | --- |
| `custom_clang_format` | *(unset)* | Enables the tool during platform configuration. Accepts `check`, `write`, `true`, `1`, `yes`, `on`. The targets work without it, but setting it keeps the tool installed for every build. |
| `custom_clang_format_dirs` | `src`, `include` | Comma-separated directories to scan. Relative paths are resolved against the project directory. |
| `custom_clang_format_extensions` | `.c, .cpp, .h, .hpp, .cc, .cxx, .ino` | Comma-separated file extensions to scan. |
| `custom_clang_format_args` | *(empty)* | Extra arguments passed to clang-format, for example `--sort-includes`. |

Scanning is recursive, so sub-directories of the configured directories are
included automatically. Keep `custom_clang_format_dirs` pointed at source
directories (for example `src, include, lib`) so build output in `.pio` and
generated code are not scanned.

### Style file

A `.clang-format` file in the project root is picked up automatically (the
targets pass `--style=file:<project>/.clang-format`). Remove the file to fall
back to clang-format's default style.

In this example the style is a slightly adapted Google style:

```yaml
---
BasedOnStyle: Google
IndentWidth: 2
ColumnLimit: 100
...
```

## CI integration

The workflow [`.github/workflows/clang-format.yml`](../../.github/workflows/clang-format.yml)
installs pioarduino and this platform from the checkout, then runs the check
for the example:

```yaml
- name: Check formatting
  run: pio run -d examples/clang-format -t clangformat
```

Because `clangformat` returns a non-zero exit code for unformatted files, the
job fails and the pull request shows the offending file, line and column:

```
src/main.cpp:1:13: error: code should be clang-formatted [-Wclang-format-violations]
```

The workflow also builds the example, so it keeps compiling with the current
development platform.

To use the same check in another CI system, install pioarduino, make the
platform available and run the target:

```shell
pip install pioarduino
pio pkg install --global --platform file://.
pio run -d examples/clang-format -t clangformat
```

Use `clangformat-write` in a pre-commit hook or a separate "format" job if you
want the CI to fix the files instead of only reporting them.
