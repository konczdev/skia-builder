# Local Build Instructions

This document provides instructions for building Skia libraries locally on Windows, Linux, and macOS.

## Prerequisites

All platforms require:
- **Python 3.x**
- **Ninja build system**
- **Git**
- **CMake**

### Platform-Specific Requirements

#### Windows
- **LLVM/Clang** - Must be installed at `C:\Program Files\LLVM\`
  - Download from: https://github.com/llvm/llvm-project/releases
  - Recommended version: 19.1.0 or later
  - During installation, select "Add LLVM to system PATH"
- **Visual Studio Build Tools** (optional, but recommended for C/C++ development)

#### Linux
Install build dependencies:
```bash
sudo apt-get update
sudo apt-get install -y libfontconfig1-dev libgl1-mesa-dev libglu1-mesa-dev libx11-xcb-dev libxcb1-dev libxcb-xkb-dev
```

#### macOS
You may need to increase the file descriptor limit:
```bash
ulimit -n 2048
```

Add this to your `~/.zshrc` or `~/.bash_profile` to make it permanent:
```bash
echo "ulimit -n 2048" >> ~/.zshrc
```

## Build Commands

### Basic Syntax
```bash
python3 build-skia.py <platform> [options]
```

### Platform Options
- `win` - Windows (x64)
- `linux` - Linux (x64)
- `mac` - macOS (universal: arm64 + x86_64)

### Common Options

#### Configuration
- `-config Debug` - Build debug configuration (default: Release)
- `-config Release` - Build release configuration

#### Skia Version
- `-branch <branch>` - Specify Skia Git branch (default: main)
  - Examples: `chrome/m144`, `chrome/m130`, `main`
  - See available branches: https://github.com/google/skia/branches

#### Build Variant
- `-variant gpu` - Build with GPU backends enabled (default)
  - Windows: Vulkan, Direct3D, OpenGL, Dawn
  - Linux: Vulkan, OpenGL, Dawn
  - macOS: Metal, OpenGL, Dawn
- `-variant cpu` - Build CPU-only (no GPU backends)

#### Clone Options
- `--shallow` - Perform shallow clone (faster, less disk space)

#### Architecture
- `-archs <arch>` - Comma-separated list of architectures
  - Windows: `x64`, `Win32`
  - Linux: `x64`, `arm64`
  - macOS: `x86_64`, `arm64`, `universal` (default)

## Example Build Commands

### Windows

#### GPU variant (recommended for C wrapper):
```bash
# Using py launcher
py -3 build-skia.py win -config Release -branch chrome/m144 -variant gpu

# Or with python3 directly
python3 build-skia.py win -config Release -branch chrome/m144 -variant gpu
```

#### CPU-only variant:
```bash
py -3 build-skia.py win -config Release -branch chrome/m144 -variant cpu
```

#### Debug build:
```bash
py -3 build-skia.py win -config Debug -branch chrome/m144 -variant gpu
```

#### Shallow clone (faster initial build):
```bash
py -3 build-skia.py win -config Release -branch chrome/m144 -variant gpu --shallow
```

### Linux

#### GPU variant:
```bash
python3 build-skia.py linux -config Release -branch chrome/m144 -variant gpu
```

#### CPU-only variant:
```bash
python3 build-skia.py linux -config Release -branch chrome/m144 -variant cpu
```

### macOS

#### Universal binary (arm64 + x86_64):
```bash
python3 build-skia.py mac -config Release -branch chrome/m144 -variant gpu
```

#### Specific architecture only:
```bash
python3 build-skia.py mac -config Release -branch chrome/m144 -variant gpu -archs arm64
```

## Build Output

After a successful build, you'll find the output in the `build/` directory:

```
build/
├── include/                           # Headers (shared across all platforms)
│   ├── core/                         # Core Skia headers
│   ├── gpu/                          # Ganesh GPU backend headers
│   ├── gpu/graphite/                 # Graphite GPU backend headers
│   ├── third_party/externals/dawn/   # Dawn/WebGPU headers (GPU variant)
│   ├── modules/skottie/              # Skottie animation headers
│   ├── modules/skshaper/             # Text shaping headers
│   └── ...
│
├── win-gpu/                          # Windows GPU variant
│   └── lib/
│       ├── Release/
│       │   └── x64/
│       │       ├── skia.lib
│       │       ├── skottie.lib
│       │       ├── sksg.lib
│       │       ├── skshaper.lib
│       │       ├── skparagraph.lib
│       │       ├── svg.lib
│       │       ├── skunicode_core.lib
│       │       ├── skunicode_icu.lib
│       │       └── dawn_combined.lib  # Dawn/WebGPU library
│       └── gn_args.txt               # Build configuration summary
│
├── linux-gpu/                        # Linux GPU variant
│   └── lib/
│       └── Release/
│           └── x64/
│               ├── libskia.a
│               ├── libskottie.a
│               ├── libdawn_combined.a
│               └── ...
│
└── mac-gpu/                          # macOS GPU variant
    └── lib/
        └── Release/
            ├── libskia.a             # Universal binary (arm64 + x86_64)
            ├── libskottie.a
            ├── libdawn_combined.a
            └── ...
```

### Output Directory Naming
- `<platform>-gpu/` - GPU-enabled build (e.g., `win-gpu`, `linux-gpu`, `mac-gpu`)
- `<platform>-cpu/` - CPU-only build (e.g., `win-cpu`, `linux-cpu`, `mac-cpu`)

## GPU Backends Enabled

### Windows GPU Variant
- **Ganesh (legacy)**:
  - Vulkan (`skia_use_vulkan = true`)
  - Direct3D (`skia_use_direct3d = true`)
  - OpenGL (`skia_use_gl = true`)
- **Graphite (modern)**:
  - Dawn WebGPU backend (`skia_use_dawn = true`)
    - Supports D3D12, Vulkan, Metal via Dawn

### Linux GPU Variant
- **Ganesh**: Vulkan, OpenGL
- **Graphite**: Dawn (Vulkan backend)

### macOS GPU Variant
- **Ganesh**: Metal, OpenGL
- **Graphite**: Dawn (Metal backend)

## Build Time and Disk Space

Approximate build times and disk usage (Release build, shallow clone):

| Platform | First Build | Incremental | Disk Space |
|----------|-------------|-------------|------------|
| Windows  | 30-60 min   | 5-15 min    | ~8 GB      |
| Linux    | 30-60 min   | 5-15 min    | ~8 GB      |
| macOS    | 45-90 min   | 10-20 min   | ~12 GB     |

Notes:
- Times vary significantly based on CPU cores and disk speed
- Universal macOS builds take longer (builds both architectures)
- Shallow clone saves ~2-3 GB compared to full clone
- Using cached depot_tools and Skia source (via GitHub Actions cache) speeds up subsequent builds

## Troubleshooting

### Windows: "clang not found"
Ensure LLVM is installed at `C:\Program Files\LLVM\` and added to PATH.

### macOS: "Too many open files"
Run `ulimit -n 2048` before building.

### Linux: Missing system libraries
Install all dependencies listed in the Prerequisites section.

### Build fails during dependency sync
Try without `--shallow` flag for a full clone:
```bash
python3 build-skia.py <platform> -config Release -branch chrome/m144
```

### Out of disk space
- Use `--shallow` flag to reduce repository size
- Clean up previous builds: `rm -rf build/tmp/`
- Use CPU variant instead of GPU variant (smaller dependencies)

### Specific branch not found
Check available branches at: https://github.com/google/skia/branches

Common stable branches:
- `chrome/m144` (current in workflow)
- `chrome/m130`
- `chrome/m129`
- `main` (latest development)

## Cleaning Build Artifacts

Remove all build outputs:
```bash
# On Unix-like systems (Linux, macOS)
rm -rf build/

# On Windows (PowerShell)
Remove-Item -Recurse -Force build\

# On Windows (cmd)
rmdir /s /q build
```

Remove only temporary build files (keep final libraries):
```bash
rm -rf build/tmp/
rm -rf build/src/
```

## Using Built Libraries in Your C Wrapper

### Link Libraries (Windows example)
```
skia.lib
dawn_combined.lib        # For Graphite WebGPU backend
skunicode_icu.lib
skparagraph.lib
skshaper.lib
```

### Include Directories
Add to your compiler include paths:
```
build/include
build/include/third_party/externals/dawn/include  # For Dawn/WebGPU
```

### Preprocessor Defines (recommended)
```cpp
SK_GANESH              // Enable Ganesh GPU backend
SK_GRAPHITE            // Enable Graphite GPU backend
SK_VULKAN              // Enable Vulkan support
SK_DIRECT3D            // Enable Direct3D support (Windows)
SK_METAL               // Enable Metal support (macOS)
SK_GL                  // Enable OpenGL support
```

## Advanced: Customizing Build Configuration

The build configuration is defined in `build-skia.py`:

### Key Constants
- `RELEASE_GN_ARGS` (line 160) - Shared release build arguments
- `PLATFORM_GN_ARGS` (line 186) - Platform-specific arguments
- `LIBS` (line 85) - Libraries to build per platform
- `GPU_LIBS` (line 114) - GPU-specific libraries (Dawn)
- `PACKAGE_DIRS` (line 123) - Header directories to include

### Example: Disable ICU, use libgrapheme instead
Edit `build-skia.py` line 82:
```python
USE_LIBGRAPHEME = True  # Change from False to True
```

### Example: Change macOS minimum version
Edit `build-skia.py` line 78:
```python
MAC_MIN_VERSION = "11.0"  # Change from "10.15"
```

## CI/CD Integration

The repository includes a GitHub Actions workflow for automated builds.

### Trigger Manual Build
```bash
gh workflow run build-skia.yml
```

### Check Build Status
```bash
gh run list
```

### Download Artifacts
Builds are published as releases tagged with the Skia branch name (e.g., `chrome/m144`).

Download from: https://github.com/YOUR_USERNAME/skia-builder/releases
