#!/usr/bin/env python3
"""
Add a `dawn_enable_dxc` GN arg that compiles Dawn's DXC code path in.

Dawn's D3D12 backend can compile HLSL with either FXC (d3dcompiler_47.dll,
shader model 5.1, DXBC) or DXC (dxcompiler.dll, shader model 6.x, DXIL).
Every line of the DXC path sits behind the DAWN_USE_BUILT_DXC preprocessor
macro, and Dawn defines that macro only together with building DXC from
source (CMake option DAWN_USE_BUILT_DXC, which also needs a full DXC
checkout and links its import library). Skia's CMake bridge passes neither,
so in a stock build the `use_dxc` toggle is forced off and FXC is the only
compiler. The macro also gates the D3D12 features that need shader model 6:
ShaderF16, Subgroups, SubgroupSizeControl and AtomicVec2uMinMax.

This patch adds the macro without the source build. Dawn does not link
against DXC at all: it opens dxcompiler.dll at device creation with
DynamicLib, searching the instance's runtime search paths (the directory of
the module Dawn is linked into comes first), and calls DxcCreateInstance.
The DXC types come from <dxcapi.h>, which d3d_platform.h already includes
from the Windows SDK in every build. So the only build change is one
preprocessor define on Dawn's translation units:

  args.gni       declares dawn_enable_dxc (default is_win)
  BUILD.gn       passes --dawn_enable_dxc=true to build_dawn.py when set
  build_dawn.py  appends -DDAWN_USE_BUILT_DXC to Dawn's C/C++ flags (Windows)

The macro is read only by src/dawn/native/d3d12 and src/dawn/platform, so a
define on every Dawn translation unit changes nothing else. With it, Dawn's
default platform answers kWebGPUUseDXC = true, so `use_dxc` defaults on for
adapters with shader model 6.0 or newer; the device's toggle descriptor can
still turn it off, which makes FXC and DXC selectable at runtime in one
build.

The runtime needs a dxcompiler.dll that signs its own output, because Dawn
no longer loads dxil.dll (Dawn b121eff3f1). Tested with a trivial vertex
and pixel shader compiled without dxil.dll in reach: the release
v1.9.2609 signs and D3D12 creates the pipeline; the Windows SDK's DXC
1.7.2308 emits an all-zero digest and D3D12 rejects the pipeline with
E_INVALIDARG. Device creation fails if use_dxc is on and dxcompiler.dll
cannot be loaded.

On by default for Windows builds: GleamUI compiles its shaders with DXC
(measured 2.18 times faster than FXC on its pipeline warmup, pixel for
pixel the same output). A build without DXC sets dawn_enable_dxc = false
in its GN args; other platforms never build the D3D12 backend and ignore
the arg.

Anchors avoid the ones apply_dawn_ios_visionos.py replaces (it runs after
this script and anchors on the Vulkan line plus closing brace in args.gni,
`args += sanitizer_args` in BUILD.gn, and the Vulkan add_argument plus
parse_args in build_dawn.py).

Retire when: Skia's Dawn bridge grows its own DXC option, or GleamUI stops
shipping the D3D12 backend.
"""

import sys
from pathlib import Path

MARKER = "dawn_enable_dxc"


def patch_args_gni(dawn_dir: Path) -> bool:
	path = dawn_dir / "args.gni"
	content = path.read_text()
	if MARKER in content:
		print("  args.gni already patched (dawn_enable_dxc)")
		return True
	anchor = "  dawn_enable_d3d12 = is_win\n"
	if anchor not in content:
		print("  Error: anchor not found in args.gni")
		return False
	insertion = (
		anchor
		+ "\n"
		+ "  # skia-builder: compile Dawn's DXC code path (DAWN_USE_BUILT_DXC)\n"
		+ "  # without building DXC; dxcompiler.dll is loaded at runtime.\n"
		+ "  dawn_enable_dxc = is_win\n"
		+ "\n"
	)
	path.write_text(content.replace(anchor, insertion, 1))
	print("  Patched args.gni (dawn_enable_dxc)")
	return True


def patch_build_gn(dawn_dir: Path) -> bool:
	path = dawn_dir / "BUILD.gn"
	content = path.read_text()
	if MARKER in content:
		print("  BUILD.gn already patched (dawn_enable_dxc)")
		return True
	anchor = (
		"  if (dawn_enable_d3d12) {\n"
		"    args += [ \"--dawn_enable_d3d12=true\" ]\n"
		"  } else {\n"
		"    args += [ \"--dawn_enable_d3d12=false\" ]\n"
		"  }\n"
	)
	if anchor not in content:
		print("  Error: anchor not found in BUILD.gn")
		return False
	insertion = (
		anchor
		+ "  if (dawn_enable_dxc) {\n"
		+ "    args += [ \"--dawn_enable_dxc=true\" ]\n"
		+ "  }\n"
	)
	path.write_text(content.replace(anchor, insertion, 1))
	print("  Patched BUILD.gn (dawn_enable_dxc)")
	return True


def patch_build_dawn_py(dawn_dir: Path) -> bool:
	path = dawn_dir / "build_dawn.py"
	content = path.read_text()
	if MARKER in content:
		print("  build_dawn.py already patched (dawn_enable_dxc)")
		return True
	argument_anchor = (
		"  parser.add_argument(\n"
		"      \"--dawn_enable_d3d12\", default=\"false\", help=\"Enable D3D12 backend.\")\n"
	)
	define_anchor = (
		"    # The D3D backend requires the HLSL writer.\n"
		"    configure_cmd.append(\"-DTINT_BUILD_HLSL_WRITER=ON\")\n"
	)
	if argument_anchor not in content or define_anchor not in content:
		print("  Error: anchor not found in build_dawn.py")
		return False
	content = content.replace(
		argument_anchor,
		argument_anchor
		+ "  parser.add_argument(\n"
		+ "      \"--dawn_enable_dxc\", default=\"false\",\n"
		+ "      help=\"Compile the D3D12 backend's DXC code path (dxcompiler.dll at runtime).\")\n",
		1)
	content = content.replace(
		define_anchor,
		define_anchor
		+ "\n"
		+ "    # skia-builder: Dawn reads DAWN_USE_BUILT_DXC only in its D3D12 backend\n"
		+ "    # and platform code; the define alone compiles the DXC path in, and\n"
		+ "    # Dawn loads dxcompiler.dll at runtime (nothing links against DXC).\n"
		+ "    if args.dawn_enable_dxc.lower() == \"true\":\n"
		+ "      cxx_flags.append(\"-DDAWN_USE_BUILT_DXC\")\n",
		1)
	path.write_text(content)
	print("  Patched build_dawn.py (dawn_enable_dxc)")
	return True


def apply_patches(skia_dir: Path) -> bool:
	dawn_dir = skia_dir / "third_party" / "dawn"
	ok = patch_args_gni(dawn_dir)
	ok = patch_build_gn(dawn_dir) and ok
	ok = patch_build_dawn_py(dawn_dir) and ok
	return ok


if __name__ == "__main__":
	if len(sys.argv) < 2:
		print("Usage: apply_dawn_dxc_option.py <skia_src_dir>")
		sys.exit(1)

	skia_dir = Path(sys.argv[1])
	if not skia_dir.exists():
		print(f"Error: Skia directory not found: {skia_dir}")
		sys.exit(1)

	print("Adding the dawn_enable_dxc option...")
	if apply_patches(skia_dir):
		print("Done!")
	else:
		print("Failed to apply patches")
		sys.exit(1)
