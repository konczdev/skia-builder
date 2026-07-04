#!/usr/bin/env python3
"""
Disable Dawn's C++20 module interface target (dawncpp_module).

Dawn (m151+) adds a CXX_MODULES file-set target when its compiler check
(DAWN_SUPPORTS_CXX_MODULES) passes. With clang-cl on Windows the check
passes (clang-scan-deps exists and a trivial module TU compiles), but CMake
cannot actually discover module import graphs for clang-cl, so the generate
step fails with:

  The target named "dawncpp_module" has C++ sources that may use modules,
  but the compiler does not provide a way to discover the import graph
  dependencies.

Skia only consumes Dawn's webgpu_cpp headers, never the C++20 module
interface, so we pre-seed the cache variable to OFF which skips the
check_cxx_source_compiles() and the whole dawncpp_module block.
"""

import sys
from pathlib import Path


def apply_patches(skia_dir: Path):
	build_dawn_py = skia_dir / "third_party" / "dawn" / "build_dawn.py"
	content = build_dawn_py.read_text()

	if "DAWN_SUPPORTS_CXX_MODULES" in content:
		print("  build_dawn.py already patched (cxx modules)")
		return True

	anchor = '      "-DDAWN_BUILD_MONOLITHIC_LIBRARY=OFF",\n'
	replacement = (
		anchor
		+ '      # CMake cannot scan C++20 module dependencies with clang-cl;\n'
		+ '      # skip Dawn\'s dawncpp_module target (Skia never imports it).\n'
		+ '      "-DDAWN_SUPPORTS_CXX_MODULES=OFF",\n'
	)
	if anchor not in content:
		print("  Error: anchor not found in build_dawn.py")
		return False

	build_dawn_py.write_text(content.replace(anchor, replacement))
	print("  Patched build_dawn.py (disable dawncpp_module)")
	return True


if __name__ == "__main__":
	if len(sys.argv) < 2:
		print("Usage: apply_dawn_disable_cxx_modules.py <skia_src_dir>")
		sys.exit(1)

	skia_dir = Path(sys.argv[1])
	if not skia_dir.exists():
		print(f"Error: Skia directory not found: {skia_dir}")
		sys.exit(1)

	print("Disabling Dawn C++20 module target...")
	if apply_patches(skia_dir):
		print("Done!")
	else:
		print("Failed to apply patches")
		sys.exit(1)
