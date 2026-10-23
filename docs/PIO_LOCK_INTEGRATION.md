# pio-lock Integration Guide

The `pio-lock` module provides dependency lockfile functionality for pioarduino, enabling **reproducible builds** for embedded projects. When enabled, it captures the exact versions of all installed dependencies and allows restoring those exact versions later.

## Overview

pio-lock scans your installed dependencies and records their exact versions in a `pio.lock.json` file that you commit alongside `platformio.ini`. Later, `restore` reinstalls those exact versions, and `check` verifies nothing has drifted.

**Captured dependencies:**
- Registry libraries — exact resolved version from `.piopm` metadata
- Git libraries — exact commit SHA from the installed repo
- Local libraries — recorded for completeness, skipped during restore
- Global packages — framework, toolchain, and tool versions from `~/.platformio/packages/`
- Platform URL — the resolved platform specification

## Enabling pio-lock

Add the following to your `platformio.ini`:

```ini
[env:myenv]
platform = https://github.com/pioarduino/platform-espressif32/releases/download/stable/platform-espressif32.zip
board = esp32dev
framework = arduino

custom_pio_lock = true
```

When `custom_pio_lock = true` is set:
1. pio-lock is automatically installed into the platform's Python virtual environment (`penv`)
2. Custom targets are automatically registered

## Available Targets

After enabling `custom_pio_lock`, the following targets become available:

### Lockfile Management

| Target | Description |
|--------|-------------|
| `lock-capture` | Capture current dependency versions into `pio.lock.json` |
| `lock-check` | Verify installed dependencies match `pio.lock.json` |
| `lock-restore` | Install exact versions from `pio.lock.json` |

### Build Snapshot Management

| Target | Description |
|--------|-------------|
| `snapshot-capture` | Save current Git HEAD to `build_snapshot.json` |
| `snapshot-check` | Verify `build_snapshot.json` matches current HEAD |
| `snapshot-clear` | Delete `build_snapshot.json` |
| `snapshot-print` | Display `build_snapshot.json` contents |

## Usage Examples

### Initial Setup and Capture

```bash
# Capture the resolved dependency state
pio run -t lock-capture -e myenv

# Commit the lockfile to version control
git add pio.lock.json
git commit -m "Add dependency lockfile"
```

### Restoring Dependencies (CI/Another Machine)

```bash
# Clone the repository (with lockfile)
git clone https://github.com/user/project.git
cd project

# Restore exact dependency versions
pio run -t lock-restore -e myenv

# Build as usual
pio run -e myenv
```

### Checking for Drift

```bash
# Verify dependencies match the lockfile (useful in CI)
pio run -t lock-check -e myenv
# Exit code: 0 = match, 1 = drift detected
```

### Working with Snapshots

```bash
# Capture current Git state
pio run -t snapshot-capture -e myenv

# Check if working directory matches snapshot
pio run -t snapshot-check -e myenv

# View snapshot contents
pio run -t snapshot-print -e myenv

# Remove snapshot
pio run -t snapshot-clear -e myenv
```

## Complete Workflow Example

### Development Machine

```bash
# Capture dependencies before committing
pio run -t lock-capture -e esp32dev

# Also capture Git state for traceability
pio run -t snapshot-capture -e esp32dev

# Commit everything
git add pio.lock.json build_snapshot.json platformio.ini
git commit -m "Feature: Add sensor driver with locked dependencies"
```

### CI/CD Pipeline

```yaml
# Example GitHub Actions workflow
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Install pioarduino
        run: pip install pioarduino
      
      - name: Restore exact dependencies
        run: pio run -t lock-restore -e esp32dev
      
      - name: Verify lockfile is up to date
        run: pio run -t lock-check -e esp32dev
      
      - name: Build firmware
        run: pio run -e esp32dev
      
      - name: Verify Git state (optional)
        run: pio run -t snapshot-check -e esp32dev
```

## Best Practices

### 1. Always Commit the Lockfile

The `pio.lock.json` file should be treated as source code and committed to version control. This ensures all team members and CI systems use identical dependencies.

```bash
git add pio.lock.json
git commit -m "Update dependencies"
```

### 2. Update Lockfile After Dependency Changes

Whenever you modify `lib_deps` in `platformio.ini` or run `pio pkg install/update`, recapture the lockfile:

```bash
pio run -t lock-capture -e myenv
```

### 3. Use Lockfile in CI

Always restore from lockfile in CI to ensure reproducible builds:

```bash
pio run -t lock-restore -e myenv
pio run -e myenv
```

### 4. Check for Drift in CI

Add a check step to detect if `platformio.ini` and `pio.lock.json` are out of sync:

```bash
pio run -t lock-check -e myenv || exit 1
```

### 5. Combine with Build Snapshots

For complete traceability, use both lockfiles and build snapshots:

```bash
# Before release builds
pio run -t lock-capture -e myenv
pio run -t snapshot-capture -e myenv
```

This creates a complete record of:
- What code was built (Git commit)
- What dependencies were used (exact versions)

## Lockfile Format

The `pio.lock.json` file contains structured dependency information:

```json
{
  "environments": {
    "esp32dev": {
      "libraries": [
        {
          "name": "ArduinoJson",
          "version": "6.21.3",
          "source": "registry"
        },
        {
          "name": "CustomLib",
          "version": "abc1234",
          "source": "git",
          "repository": "https://github.com/user/lib.git"
        }
      ],
      "packages": {
        "tool-esptoolpy": "5.2.0"
      },
      "platform": "https://github.com/pioarduino/platform-espressif32/releases/download/55.03.38/platform-espressif32.zip"
    }
  }
}
```

## Troubleshooting

### Lock restore fails

If `lock-restore` fails due to missing packages:

```bash
# WARNING: This removes lib_deps, platform, framework, toolchains and tools
# for the env, forcing a full re-download on the next run.
pio pkg uninstall -e myenv
pio run -t lock-restore -e myenv
```

### Outdated lockfile

If `lock-check` reports drift:

```bash
# Review changes, then update lockfile
pio run -t lock-capture -e myenv
```

## See Also

- [pio-lock GitHub Repository](https://github.com/m-mcgowan/pio-lock)
