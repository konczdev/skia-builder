#!/usr/bin/env python3

"""
build-viewer.py

This script builds the Skia Viewer application for desktop platforms
(macOS, Windows, Linux). The viewer is Skia's demo application that
showcases various rendering features and allows testing different backends.

Usage:
    python3 build-viewer.py <platform> [options]

For detailed usage instructions, run:
    python3 build-viewer.py --help

Based on build-skia.py - Copyright (c) 2024-2026 Oli Larkin
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

# Shared constants
BASE_DIR = Path(__file__).resolve().parent / "build"
DEPOT_TOOLS_PATH = BASE_DIR / "tmp" / "depot_tools"
DEPOT_TOOLS_URL = "https://chromium.googlesource.com/chromium/tools/depot_tools.git"
SKIA_GIT_URL = "https://github.com/google/skia.git"
SKIA_SRC_DIR = BASE_DIR / "src" / "skia"
TMP_DIR = BASE_DIR / "tmp" / "skia"

# Platform-specific constants
MAC_MIN_VERSION = "10.15"

# Dependencies to exclude during sync (same as build-skia.py)
EXCLUDE_DEPS = [
    "third_party/externals/emsdk",
    "third_party/externals/v8",
    "third_party/externals/oboe",
    # Note: imgui is required for viewer, so don't exclude it
    "third_party/externals/dng_sdk",
    "third_party/externals/microhttpd",
]

BASIC_GN_ARGS = """
cc = "clang"
cxx = "clang++"
"""

# GN args for building the viewer application
# The viewer requires Ganesh or Graphite, and uses imgui for its UI
VIEWER_GN_ARGS = """
skia_use_system_libjpeg_turbo = false
skia_use_system_libpng = false
skia_use_system_zlib = false
skia_use_system_expat = false
skia_use_system_icu = false
skia_use_system_harfbuzz = false
skia_use_system_libwebp = false

skia_use_libwebp_decode = true
skia_use_libwebp_encode = false
skia_use_xps = false
skia_use_dng_sdk = false
skia_use_expat = true
skia_use_icu = true
skia_use_libgrapheme = false

skia_enable_ganesh = true
skia_enable_graphite = true
skia_enable_svg = true
skia_enable_skottie = true
skia_enable_pdf = false
skia_enable_skparagraph = true
skia_enable_tools = true
"""

# Platform-specific GN args for viewer
PLATFORM_GN_ARGS = {
    "mac": f"""
    skia_use_gl = true
    skia_use_metal = true
    skia_use_dawn = true
    target_os = "mac"
    extra_cflags_c = ["-Wno-error"]
    extra_cflags_cc = ["-frtti"]
    mac_deployment_target = "{MAC_MIN_VERSION}"
    """,

    "win": """
    skia_use_gl = true
    skia_use_dawn = true
    skia_use_direct3d = true
    skia_use_vulkan = true
    is_trivial_abi = false
    extra_cflags_cc = ["/GR"]
    """,

    "linux": """
    skia_use_gl = true
    skia_use_vulkan = true
    skia_use_dawn = true
    skia_use_x11 = true
    skia_use_fontconfig = true
    skia_use_freetype = true
    skia_use_system_freetype2 = false
    extra_cflags_c = ["-Wno-error"]
    extra_cflags_cc = ["-frtti"]
    """
}


class SkiaViewerBuildScript:
    def __init__(self):
        self.platform = None
        self.config = "Release"
        self.arch = None
        self.branch = None
        self.backend = None  # Preferred rendering backend

    def parse_arguments(self):
        parser = argparse.ArgumentParser(
            description="Build Skia Viewer for macOS, Windows, and Linux",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
    python3 build-viewer.py mac                    # Build for macOS
    python3 build-viewer.py win                    # Build for Windows
    python3 build-viewer.py linux                  # Build for Linux
    python3 build-viewer.py mac -config Debug     # Debug build
    python3 build-viewer.py mac -branch chrome/m144  # Specific Skia branch

After building, run the viewer:
    ./build/viewer/mac/viewer --resourcePath ./build/src/skia/resources
    ./build/viewer/mac/viewer --backend mtl   # Use Metal backend
    ./build/viewer/mac/viewer --backend gl    # Use OpenGL backend
"""
        )
        parser.add_argument("platform", choices=["mac", "win", "linux"],
                           help="Target platform")
        parser.add_argument("-config", choices=["Debug", "Release"],
                           default="Release", help="Build configuration")
        parser.add_argument("-arch", help="Target architecture (default: native)")
        parser.add_argument("-branch", help="Skia Git branch to checkout",
                           default="main")
        parser.add_argument("--shallow", action="store_true",
                           help="Perform a shallow clone of the Skia repository")
        args = parser.parse_args()

        self.platform = args.platform
        self.config = args.config
        self.branch = args.branch
        self.shallow_clone = args.shallow

        # Set default architecture based on platform
        if args.arch:
            self.arch = args.arch
        else:
            self.arch = self.get_default_arch()

    def get_default_arch(self):
        if self.platform == "mac":
            # Build for native architecture
            import platform
            machine = platform.machine()
            return "arm64" if machine == "arm64" else "x64"
        elif self.platform == "win":
            return "x64"
        elif self.platform == "linux":
            return "x64"

    def get_output_dir(self):
        """Get the output directory for the viewer executable."""
        return BASE_DIR / "viewer" / self.platform

    def get_build_dir(self):
        """Get the ninja build directory."""
        return TMP_DIR / f"viewer_{self.platform}_{self.config}_{self.arch}"

    def setup_depot_tools(self):
        """Clone depot_tools if not present and add to PATH."""
        if not DEPOT_TOOLS_PATH.exists():
            colored_print("Cloning depot_tools...", Colors.OKBLUE)
            subprocess.run(["git", "clone", DEPOT_TOOLS_URL, str(DEPOT_TOOLS_PATH)],
                         check=True)
        os.environ["PATH"] = f"{DEPOT_TOOLS_PATH}:{os.environ['PATH']}"

    def setup_skia_repo(self):
        """Clone or update Skia repository."""
        colored_print(f"Setting up Skia repository (branch: {self.branch})...",
                     Colors.OKBLUE)
        if not SKIA_SRC_DIR.exists():
            clone_command = ["git", "clone"]
            if self.shallow_clone:
                clone_command.extend(["--depth", "1"])
            clone_command.extend(["--branch", self.branch, SKIA_GIT_URL,
                                str(SKIA_SRC_DIR)])
            subprocess.run(clone_command, check=True)
        else:
            os.chdir(SKIA_SRC_DIR)
            fetch_command = ["git", "fetch"]
            if self.shallow_clone:
                fetch_command.extend(["--depth", "1"])
            fetch_command.extend(["origin", self.branch])
            subprocess.run(fetch_command, check=True)
            subprocess.run(["git", "checkout", self.branch], check=True)
            subprocess.run(["git", "reset", "--hard", f"origin/{self.branch}"],
                         check=True)
        colored_print("Skia repository setup complete.", Colors.OKGREEN)

    def sync_deps(self):
        """Sync Skia dependencies."""
        os.chdir(SKIA_SRC_DIR)
        colored_print("Syncing dependencies...", Colors.OKBLUE)
        subprocess.run([sys.executable, "tools/git-sync-deps"], check=True)
        colored_print("Dependencies synced.", Colors.OKGREEN)

    def generate_gn_args(self):
        """Generate GN arguments for the viewer build."""
        build_dir = self.get_build_dir()

        gn_args = BASIC_GN_ARGS
        gn_args += PLATFORM_GN_ARGS[self.platform]
        gn_args += VIEWER_GN_ARGS

        # Configuration settings
        if self.config == 'Debug':
            gn_args += "is_debug = true\n"
            gn_args += "is_official_build = false\n"
        else:
            gn_args += "is_debug = false\n"
            gn_args += "is_official_build = true\n"

        # Architecture settings
        if self.platform == "mac":
            gn_args += f'target_cpu = "{self.arch}"\n'
        elif self.platform == "win":
            # Map architecture names to GN target_cpu values
            if self.arch == "Win32":
                gn_args += 'target_cpu = "x86"\n'
            elif self.arch == "arm64":
                gn_args += 'target_cpu = "arm64"\n'
                # OpenGL is not supported on Windows ARM64
                gn_args += "skia_use_gl = false\n"
            else:  # x64
                gn_args += 'target_cpu = "x64"\n'

            # Find Clang installation
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
                gn_args += f'clang_win = "{clang_win}"\n'
            else:
                colored_print("Warning: Clang/LLVM not found - build may fail",
                            Colors.WARNING)
        elif self.platform == "linux":
            gn_args += f'target_cpu = "{"arm64" if self.arch == "arm64" else "x64"}"\n'

        colored_print(f"Generating GN args for {self.platform} viewer:", Colors.OKBLUE)
        colored_print(gn_args, Colors.OKCYAN)

        os.chdir(SKIA_SRC_DIR)
        subprocess.run(["./bin/gn", "gen", str(build_dir), f"--args={gn_args}"],
                      check=True)

    def build_viewer(self):
        """Build the viewer application using ninja."""
        build_dir = self.get_build_dir()

        colored_print(f"Building viewer for {self.platform}...", Colors.OKBLUE)

        try:
            subprocess.run(["ninja", "-C", str(build_dir), "viewer"], check=True)
            colored_print(f"Successfully built viewer for {self.platform}",
                        Colors.OKGREEN)
        except subprocess.CalledProcessError as e:
            colored_print(f"Error: Build failed for {self.platform}", Colors.FAIL)
            print(f"Error details: {e}")
            sys.exit(1)

    def copy_viewer(self):
        """Copy the viewer executable to the output directory."""
        build_dir = self.get_build_dir()
        output_dir = self.get_output_dir()
        output_dir.mkdir(parents=True, exist_ok=True)

        # Platform-specific executable names
        if self.platform == "mac":
            # On macOS, viewer is an app bundle
            src_app = build_dir / "viewer.app"
            src_exe = build_dir / "viewer"

            if src_app.exists():
                dest_app = output_dir / "viewer.app"
                if dest_app.exists():
                    shutil.rmtree(dest_app)
                shutil.copytree(src_app, dest_app)
                colored_print(f"Copied viewer.app to {output_dir}", Colors.OKGREEN)
            elif src_exe.exists():
                dest_exe = output_dir / "viewer"
                shutil.copy2(src_exe, dest_exe)
                # Make executable
                os.chmod(dest_exe, 0o755)
                colored_print(f"Copied viewer to {output_dir}", Colors.OKGREEN)
            else:
                colored_print("Warning: viewer executable not found", Colors.WARNING)

        elif self.platform == "win":
            src_exe = build_dir / "viewer.exe"
            if src_exe.exists():
                dest_exe = output_dir / "viewer.exe"
                shutil.copy2(src_exe, dest_exe)
                colored_print(f"Copied viewer.exe to {output_dir}", Colors.OKGREEN)

                # Copy any required DLLs
                for dll in build_dir.glob("*.dll"):
                    shutil.copy2(dll, output_dir / dll.name)
            else:
                colored_print("Warning: viewer.exe not found", Colors.WARNING)

        elif self.platform == "linux":
            src_exe = build_dir / "viewer"
            if src_exe.exists():
                dest_exe = output_dir / "viewer"
                shutil.copy2(src_exe, dest_exe)
                os.chmod(dest_exe, 0o755)
                colored_print(f"Copied viewer to {output_dir}", Colors.OKGREEN)
            else:
                colored_print("Warning: viewer executable not found", Colors.WARNING)

        # Copy resources directory for convenience
        resources_src = SKIA_SRC_DIR / "resources"
        resources_dest = output_dir / "resources"
        if resources_src.exists() and not resources_dest.exists():
            # Create symlink to resources instead of copying (saves space)
            try:
                resources_dest.symlink_to(resources_src)
                colored_print(f"Created symlink to resources at {resources_dest}",
                            Colors.OKGREEN)
            except OSError:
                # Symlinks may not work on all systems, fall back to info message
                colored_print(f"Resources available at: {resources_src}", Colors.OKCYAN)

    def print_usage_info(self):
        """Print information about how to run the viewer."""
        output_dir = self.get_output_dir()

        colored_print("\n" + "="*60, Colors.HEADER)
        colored_print("Viewer build complete!", Colors.OKGREEN)
        colored_print("="*60, Colors.HEADER)

        if self.platform == "mac":
            exe_path = output_dir / "viewer"
            if (output_dir / "viewer.app").exists():
                exe_path = output_dir / "viewer.app" / "Contents" / "MacOS" / "viewer"
            colored_print(f"\nRun the viewer:", Colors.OKBLUE)
            colored_print(f"  {exe_path} --resourcePath {SKIA_SRC_DIR / 'resources'}",
                        Colors.OKCYAN)
            colored_print(f"\nBackend options:", Colors.OKBLUE)
            colored_print(f"  --backend mtl   # Metal (recommended on macOS)", Colors.OKCYAN)
            colored_print(f"  --backend gl    # OpenGL", Colors.OKCYAN)
            colored_print(f"  --backend vk    # Vulkan (if available)", Colors.OKCYAN)
        elif self.platform == "win":
            colored_print(f"\nRun the viewer:", Colors.OKBLUE)
            colored_print(f"  {output_dir / 'viewer.exe'} --resourcePath {SKIA_SRC_DIR / 'resources'}",
                        Colors.OKCYAN)
            colored_print(f"\nBackend options:", Colors.OKBLUE)
            colored_print(f"  --backend d3d   # Direct3D", Colors.OKCYAN)
            colored_print(f"  --backend gl    # OpenGL", Colors.OKCYAN)
            colored_print(f"  --backend vk    # Vulkan", Colors.OKCYAN)
            colored_print(f"  --backend angle # ANGLE (for ARM64)", Colors.OKCYAN)
        elif self.platform == "linux":
            colored_print(f"\nRun the viewer:", Colors.OKBLUE)
            colored_print(f"  {output_dir / 'viewer'} --resourcePath {SKIA_SRC_DIR / 'resources'}",
                        Colors.OKCYAN)
            colored_print(f"\nBackend options:", Colors.OKBLUE)
            colored_print(f"  --backend gl    # OpenGL", Colors.OKCYAN)
            colored_print(f"  --backend vk    # Vulkan", Colors.OKCYAN)

        colored_print(f"\nOther useful options:", Colors.OKBLUE)
        colored_print(f"  --slide <n>     # Start at slide n", Colors.OKCYAN)
        colored_print(f"  --match <name>  # Load only matching slides/SKPs", Colors.OKCYAN)
        colored_print(f"  --skps <path>   # Load .skp files from directory", Colors.OKCYAN)

    def apply_patches(self):
        """Apply any patches from the patches directory."""
        patches_dir = Path(__file__).resolve().parent / "patches"
        if not patches_dir.exists():
            return

        os.chdir(SKIA_SRC_DIR)

        # Apply .patch files using git apply
        for patch_file in sorted(patches_dir.glob("*.patch")):
            colored_print(f"Applying patch: {patch_file.name}", Colors.OKBLUE)
            try:
                # Check if patch is already applied
                result = subprocess.run(
                    ["git", "apply", "--check", "--reverse", str(patch_file)],
                    capture_output=True, text=True
                )
                if result.returncode == 0:
                    colored_print(f"  Patch {patch_file.name} already applied, skipping.",
                                Colors.OKCYAN)
                    continue

                # Apply the patch
                subprocess.run(["git", "apply", str(patch_file)], check=True)
                colored_print(f"  Applied {patch_file.name} successfully.", Colors.OKGREEN)
            except subprocess.CalledProcessError as e:
                colored_print(f"  Warning: Failed to apply {patch_file.name}: {e}",
                            Colors.WARNING)

        # Apply Python patch scripts
        for patch_script in sorted(patches_dir.glob("apply_*.py")):
            colored_print(f"Running patch script: {patch_script.name}", Colors.OKBLUE)
            try:
                subprocess.run([sys.executable, str(patch_script), str(SKIA_SRC_DIR)],
                             check=True)
                colored_print(f"  Ran {patch_script.name} successfully.", Colors.OKGREEN)
            except subprocess.CalledProcessError as e:
                colored_print(f"  Warning: Failed to run {patch_script.name}: {e}",
                            Colors.WARNING)

    def run(self):
        """Main entry point."""
        self.parse_arguments()

        colored_print(f"\nBuilding Skia Viewer for {self.platform} ({self.config})",
                     Colors.HEADER)
        colored_print(f"Architecture: {self.arch}", Colors.OKBLUE)
        colored_print(f"Branch: {self.branch}\n", Colors.OKBLUE)

        self.setup_depot_tools()
        self.setup_skia_repo()
        self.sync_deps()
        self.apply_patches()
        self.generate_gn_args()
        self.build_viewer()
        self.copy_viewer()
        self.print_usage_info()


if __name__ == "__main__":
    SkiaViewerBuildScript().run()
