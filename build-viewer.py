#!/usr/bin/env python3

"""
build-viewer.py

Builds the Skia Viewer application for macOS, Windows, and Linux.
Must be run after build-skia.py has cloned the Skia repo and synced deps.

Usage:
    python3 build-viewer.py <platform> [options]

For detailed usage instructions, run:
    python3 build-viewer.py --help

Copyright (c) 2024-2026 Oli Larkin

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Define ANSI color codes
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def colored_print(message, color):
    print(f"{color}{message}{Colors.ENDC}")

# Shared constants (matching build-skia.py)
BASE_DIR = Path(__file__).resolve().parent / "build"
DEPOT_TOOLS_PATH = BASE_DIR / "tmp" / "depot_tools"
SKIA_SRC_DIR = BASE_DIR / "src" / "skia"
TMP_DIR = BASE_DIR / "tmp" / "viewer"

# Available backends per platform
PLATFORM_BACKENDS = {
    "mac": {
        "gl": True,       # OpenGL (Ganesh only)
        "metal": True,    # Metal (Ganesh + Graphite)
        "vulkan": False,  # Not recommended on macOS
        "dawn": True,     # Dawn/WebGPU (Graphite only)
    },
    "win": {
        "gl": True,       # OpenGL (Ganesh only)
        "vulkan": True,   # Vulkan (Ganesh + Graphite)
        "d3d": True,      # Direct3D 12 (Ganesh only)
        "dawn": True,     # Dawn/WebGPU (Graphite only)
    },
    "linux": {
        "gl": True,       # OpenGL (Ganesh only)
        "vulkan": True,   # Vulkan (Ganesh + Graphite)
        "dawn": True,     # Dawn/WebGPU (Graphite only)
    },
}

# Default backends per platform
DEFAULT_BACKENDS = {
    "mac": ["gl", "metal", "dawn"],
    "win": ["gl", "vulkan", "d3d", "dawn"],
    "linux": ["gl", "vulkan", "dawn"],
}

# Base GN arguments for viewer (all platforms)
VIEWER_BASE_GN_ARGS = """
skia_enable_tools = true

skia_enable_ganesh = {ganesh}
skia_enable_graphite = {graphite}

skia_use_libjpeg_turbo_decode = true
skia_use_libpng_decode = true
skia_use_libpng_encode = true
skia_use_libwebp_decode = true
skia_use_wuffs = true

skia_use_icu = true
skia_use_harfbuzz = true
skia_enable_skparagraph = true
skia_enable_skshaper = true

skia_enable_skottie = true
skia_enable_svg = true
skia_enable_pdf = true

skia_use_system_libjpeg_turbo = false
skia_use_system_libpng = false
skia_use_system_zlib = false
skia_use_system_expat = false
skia_use_system_icu = false
skia_use_system_harfbuzz = false
skia_use_system_libwebp = false

skia_use_expat = true
"""

# Platform-specific GN arguments
PLATFORM_GN_ARGS = {
    "mac": """
cc = "clang"
cxx = "clang++"
target_os = "mac"
target_cpu = "{arch}"

skia_use_gl = {use_gl}
skia_use_metal = {use_metal}
skia_use_vulkan = false
skia_use_dawn = {use_dawn}

extra_cflags_c = ["-Wno-error"]
extra_cflags_cc = ["-stdlib=libc++"]
extra_ldflags = ["-stdlib=libc++", "-L/opt/homebrew/opt/llvm/lib/c++", "-L/opt/homebrew/opt/llvm/lib/unwind", "-lunwind"]
""",

    "win": """
target_cpu = "{arch}"

skia_use_gl = {use_gl}
skia_use_vulkan = {use_vulkan}
skia_use_direct3d = {use_d3d}
skia_use_dawn = {use_dawn}
skia_use_metal = false

is_trivial_abi = false
extra_cflags = ["{runtime_flag}"]
""",

    "linux": """
cc = "clang"
cxx = "clang++"
target_cpu = "{arch}"

skia_use_gl = {use_gl}
skia_use_vulkan = {use_vulkan}
skia_use_dawn = {use_dawn}
skia_use_metal = false
skia_use_direct3d = false

skia_use_x11 = true
skia_use_fontconfig = true
skia_use_freetype = true
skia_use_system_freetype2 = false

extra_cflags_c = ["-Wno-error"]
"""
}

# Resource directories to copy
RESOURCE_DIRS = [
    "fonts",
    "images",
    "skottie",
    "sksl",
    "text",
    "svg",
]


class ViewerBuildScript:
    def __init__(self):
        self.platform = None
        self.config = "Release"
        self.arch = None
        self.backends = []
        self.with_ganesh = True
        self.with_graphite = True
        self.with_resources = True
        self.clean = False

    def parse_arguments(self):
        parser = argparse.ArgumentParser(
            description="Build Skia Viewer application"
        )
        parser.add_argument(
            "platform",
            choices=["mac", "win", "linux"],
            help="Target platform"
        )
        parser.add_argument(
            "-config",
            choices=["Debug", "Release"],
            default="Release",
            help="Build configuration (default: Release)"
        )
        parser.add_argument(
            "-arch",
            help="Target architecture (mac: arm64, win: x64/arm64, linux: x64/arm64)"
        )
        parser.add_argument(
            "-backends",
            help="Comma-separated GPU backends (e.g., gl,metal,dawn)"
        )
        parser.add_argument(
            "--no-ganesh",
            action="store_true",
            help="Disable Ganesh rendering engine"
        )
        parser.add_argument(
            "--no-graphite",
            action="store_true",
            help="Disable Graphite rendering engine"
        )
        parser.add_argument(
            "--no-resources",
            action="store_true",
            help="Skip copying resources directory"
        )
        parser.add_argument(
            "--clean",
            action="store_true",
            help="Clean build directory before building"
        )

        args = parser.parse_args()
        self.platform = args.platform
        self.config = args.config
        self.arch = args.arch or self.get_default_arch()
        self.backends = self.parse_backends(args.backends)
        self.with_ganesh = not args.no_ganesh
        self.with_graphite = not args.no_graphite
        self.with_resources = not args.no_resources
        self.clean = args.clean

        self.validate_configuration()

    def get_default_arch(self):
        if self.platform == "mac":
            return "arm64"
        elif self.platform == "win":
            return "x64"
        else:
            return "x64"

    def parse_backends(self, backends_str):
        if backends_str:
            return [b.strip().lower() for b in backends_str.split(",")]
        return DEFAULT_BACKENDS.get(self.platform, [])

    def validate_configuration(self):
        # Validate at least one rendering engine
        if not self.with_ganesh and not self.with_graphite:
            colored_print(
                "Error: Viewer requires at least Ganesh or Graphite enabled",
                Colors.FAIL
            )
            sys.exit(1)

        # Validate backends
        available = PLATFORM_BACKENDS.get(self.platform, {})
        valid_backends = []
        for backend in self.backends:
            if backend not in available:
                colored_print(
                    f"Warning: Backend '{backend}' not recognized for {self.platform}, skipping",
                    Colors.WARNING
                )
            elif not available[backend]:
                colored_print(
                    f"Warning: Backend '{backend}' not recommended on {self.platform}, skipping",
                    Colors.WARNING
                )
            else:
                valid_backends.append(backend)
        self.backends = valid_backends

        if not self.backends:
            colored_print(
                "Error: No valid backends selected",
                Colors.FAIL
            )
            sys.exit(1)

        # Dawn requires Graphite
        if "dawn" in self.backends and not self.with_graphite:
            colored_print(
                "Warning: Dawn requires Graphite. Enabling Graphite.",
                Colors.WARNING
            )
            self.with_graphite = True

        # Validate architecture
        valid_archs = {
            "mac": ["arm64"],
            "win": ["x64", "arm64"],
            "linux": ["x64", "arm64"],
        }
        if self.arch not in valid_archs.get(self.platform, []):
            colored_print(
                f"Error: Invalid architecture '{self.arch}' for {self.platform}",
                Colors.FAIL
            )
            sys.exit(1)

    def verify_prerequisites(self):
        """Verify that build-skia.py has been run."""
        if not SKIA_SRC_DIR.exists():
            colored_print(
                "Error: Skia source not found at " + str(SKIA_SRC_DIR),
                Colors.FAIL
            )
            colored_print(
                "Please run build-skia.py first to clone and sync Skia.",
                Colors.WARNING
            )
            sys.exit(1)

        # Check for synced dependencies (imgui is required for viewer)
        imgui_dir = SKIA_SRC_DIR / "third_party" / "externals" / "imgui"
        if not imgui_dir.exists():
            colored_print(
                "Error: Skia dependencies not synced (imgui not found)",
                Colors.FAIL
            )
            colored_print(
                "Please run build-skia.py first to sync dependencies.",
                Colors.WARNING
            )
            sys.exit(1)

        if not DEPOT_TOOLS_PATH.exists():
            colored_print(
                "Error: depot_tools not found at " + str(DEPOT_TOOLS_PATH),
                Colors.FAIL
            )
            colored_print(
                "Please run build-skia.py first to set up depot_tools.",
                Colors.WARNING
            )
            sys.exit(1)

        colored_print("Prerequisites verified.", Colors.OKGREEN)

    def setup_depot_tools(self):
        """Add depot_tools to PATH."""
        os.environ["PATH"] = f"{DEPOT_TOOLS_PATH}:{os.environ['PATH']}"

    def generate_gn_args(self):
        """Generate GN args and create build directory."""
        output_dir = TMP_DIR / f"{self.platform}_{self.config}_{self.arch}"

        if self.clean and output_dir.exists():
            colored_print(f"Cleaning {output_dir}...", Colors.OKBLUE)
            shutil.rmtree(output_dir)

        # Combine base args with platform-specific args
        gn_args = VIEWER_BASE_GN_ARGS.format(
            ganesh="true" if self.with_ganesh else "false",
            graphite="true" if self.with_graphite else "false",
        )

        # Add platform-specific args
        platform_args = PLATFORM_GN_ARGS[self.platform].format(
            arch=self.arch,
            use_gl="true" if "gl" in self.backends else "false",
            use_metal="true" if "metal" in self.backends else "false",
            use_vulkan="true" if "vulkan" in self.backends else "false",
            use_d3d="true" if "d3d" in self.backends else "false",
            use_dawn="true" if "dawn" in self.backends else "false",
            runtime_flag="/MTd" if self.config == "Debug" else "/MT",
        )
        gn_args += platform_args

        # Add debug/release settings
        # Note: Viewer requires is_official_build=false to enable GPU_TEST_UTILS
        # which is needed for viewer's GPU debugging tools
        if self.config == "Debug":
            gn_args += "\nis_debug = true\n"
        else:
            gn_args += "\nis_debug = false\n"
        gn_args += "is_official_build = false\n"

        # Add Windows Clang path if needed
        if self.platform == "win":
            clang_paths = [
                "C:\\Program Files\\LLVM",
                "C:\\Program Files\\Microsoft Visual Studio\\2022\\Professional\\VC\\Tools\\Llvm\\x64",
                "C:\\Program Files\\Microsoft Visual Studio\\2022\\Community\\VC\\Tools\\Llvm\\x64",
                "C:\\Program Files\\Microsoft Visual Studio\\2022\\Enterprise\\VC\\Tools\\Llvm\\x64",
            ]
            clang_win = None
            for path in clang_paths:
                if os.path.isdir(path):
                    clang_win = path
                    break
            if clang_win:
                gn_args += f'\nclang_win = "{clang_win}"\n'
            else:
                colored_print("Warning: Clang/LLVM not found - build may fail", Colors.WARNING)

        colored_print(f"Generating GN args for {self.platform} {self.arch}...", Colors.OKBLUE)
        colored_print(f"Backends: {', '.join(self.backends)}", Colors.OKCYAN)
        colored_print(f"Ganesh: {self.with_ganesh}, Graphite: {self.with_graphite}", Colors.OKCYAN)

        os.chdir(SKIA_SRC_DIR)
        gn_cmd = ["./bin/gn", "gen", str(output_dir), f"--args={gn_args}"]
        if self.platform == "win":
            gn_cmd[0] = str(SKIA_SRC_DIR / "bin" / "gn.exe")

        subprocess.run(gn_cmd, check=True)

        return output_dir

    def build_viewer(self, output_dir):
        """Build the viewer target using ninja."""
        colored_print(f"Building viewer for {self.platform} {self.arch}...", Colors.OKBLUE)
        try:
            subprocess.run(
                ["ninja", "-C", str(output_dir), "viewer"],
                check=True
            )
            colored_print("Viewer built successfully.", Colors.OKGREEN)
        except subprocess.CalledProcessError as e:
            colored_print(f"Error: Build failed", Colors.FAIL)
            print(f"Error details: {e}")
            sys.exit(1)

    def get_output_dir(self):
        """Get the final output directory for the viewer."""
        variant = "gpu" if (self.with_ganesh or self.with_graphite) else "cpu"
        viewer_dir = BASE_DIR / f"viewer-{variant}"

        if self.platform == "mac":
            return viewer_dir / "mac" / self.config
        else:
            return viewer_dir / self.platform / self.config / self.arch

    def copy_output(self, build_dir):
        """Copy built viewer to final output location."""
        dest_dir = self.get_output_dir()
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Determine executable name
        if self.platform == "win":
            exe_name = "viewer.exe"
        else:
            exe_name = "viewer"

        src_file = build_dir / exe_name
        dest_file = dest_dir / exe_name

        if src_file.exists():
            shutil.copy2(src_file, dest_file)
            colored_print(f"Copied {exe_name} to {dest_dir}", Colors.OKGREEN)

            # Make executable on Unix
            if self.platform != "win":
                os.chmod(dest_file, 0o755)
        else:
            colored_print(f"Error: {exe_name} not found in {build_dir}", Colors.FAIL)
            sys.exit(1)

    def copy_resources(self):
        """Copy Skia resources for viewer demos."""
        src_resources = SKIA_SRC_DIR / "resources"
        dest_resources = BASE_DIR / "resources"

        if not src_resources.exists():
            colored_print("Warning: Skia resources directory not found", Colors.WARNING)
            return

        colored_print("Copying resources...", Colors.OKBLUE)

        # Create destination directory
        dest_resources.mkdir(parents=True, exist_ok=True)

        # Copy selective directories
        for dir_name in RESOURCE_DIRS:
            src_dir = src_resources / dir_name
            dest_dir = dest_resources / dir_name
            if src_dir.exists():
                if dest_dir.exists():
                    shutil.rmtree(dest_dir)
                shutil.copytree(src_dir, dest_dir)
                colored_print(f"  Copied resources/{dir_name}", Colors.OKCYAN)

        colored_print("Resources copied.", Colors.OKGREEN)

    def create_launcher_script(self):
        """Create a launcher script that sets resourcePath automatically."""
        dest_dir = self.get_output_dir()
        resources_path = BASE_DIR / "resources"

        if self.platform == "win":
            # Windows batch file
            launcher_path = dest_dir / "run-viewer.bat"
            # Use relative path from the batch file location
            rel_resources = os.path.relpath(resources_path, dest_dir)
            content = f'''@echo off
cd /d "%~dp0"
viewer.exe --resourcePath "{rel_resources}" %*
'''
        else:
            # Unix shell script
            launcher_path = dest_dir / "run-viewer.sh"
            # Use relative path from the script location
            rel_resources = os.path.relpath(resources_path, dest_dir)
            content = f'''#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
"$SCRIPT_DIR/viewer" --resourcePath "$SCRIPT_DIR/{rel_resources}" "$@"
'''

        with open(launcher_path, "w") as f:
            f.write(content)

        # Make executable on Unix
        if self.platform != "win":
            os.chmod(launcher_path, 0o755)

        colored_print(f"Created launcher: {launcher_path}", Colors.OKGREEN)

    def print_success(self):
        """Print success message with run instructions."""
        dest_dir = self.get_output_dir()

        if self.platform == "win":
            launcher = dest_dir / "run-viewer.bat"
        else:
            launcher = dest_dir / "run-viewer.sh"

        colored_print("\n" + "=" * 60, Colors.OKGREEN)
        colored_print("Viewer built successfully!", Colors.OKGREEN)
        colored_print("=" * 60, Colors.OKGREEN)
        colored_print(f"\nPlatform: {self.platform}", Colors.OKCYAN)
        colored_print(f"Architecture: {self.arch}", Colors.OKCYAN)
        colored_print(f"Configuration: {self.config}", Colors.OKCYAN)
        colored_print(f"Backends: {', '.join(self.backends)}", Colors.OKCYAN)
        colored_print(f"\nTo run the viewer:", Colors.OKBLUE)
        colored_print(f"  {launcher}", Colors.BOLD)
        colored_print("\nViewer controls:", Colors.OKBLUE)
        colored_print("  b - Change backend (GL/Metal/Vulkan/Dawn)", Colors.OKCYAN)
        colored_print("  s - Change slide", Colors.OKCYAN)
        colored_print("  Space - Toggle stats overlay", Colors.OKCYAN)
        colored_print("  h - Toggle help", Colors.OKCYAN)

    def run(self):
        """Main execution flow."""
        self.parse_arguments()
        self.verify_prerequisites()
        self.setup_depot_tools()
        output_dir = self.generate_gn_args()
        self.build_viewer(output_dir)
        self.copy_output(output_dir)
        if self.with_resources:
            self.copy_resources()
        self.create_launcher_script()
        self.print_success()


if __name__ == "__main__":
    ViewerBuildScript().run()
