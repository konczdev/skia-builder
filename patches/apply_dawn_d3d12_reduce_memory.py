#!/usr/bin/env python3
"""
Give Dawn's D3D12 backend a working ReduceMemoryUsage.

dawn::native::ReduceMemoryUsage dispatches to a per-backend
ReduceMemoryUsageImpl, which only D3D11 and Vulkan override — the base
returns false, so on D3D12 the call never touches the heap pool. The
pool (PooledResourceMemoryAllocator::mPool) is unbounded, and its only
release point, ResourceAllocatorManager::FreeRecycledAllocations(), is
called solely from the manager's destructor. A long-lived device
therefore keeps the committed-heap peak of every resize burst until the
process exits (measured: a table demo idling at 60 MB dedicated GPU
pinned 837 MB after an interactive window resize, with the dump showing
33 MB used against 494 MB allocated heaps).

This patch adds the D3D12 override, mirroring the Vulkan backend's
shape (FreeRecycledMemory there): tick the allocator so serial-deferred
deletions reach the recycle pool, then free every pooled heap. It also
moves FreeRecycledAllocations() to the manager's public section, the
visibility its Vulkan sibling already has.

Retire when upstream implements a D3D12 ReduceMemoryUsageImpl of its
own (crbug.com/398193014 tracks follow-up work in this area).
"""

import sys
from pathlib import Path


def patch_allocator_header(dawn_native: Path) -> bool:
	header = dawn_native / "d3d12" / "ResourceAllocatorManagerD3D12.h"
	content = header.read_text()

	public_anchor = "    void Tick(ExecutionSerial lastCompletedSerial);\n"
	private_decl = "    void FreeRecycledAllocations();\n"

	if content.find("FreeRecycledAllocations") < content.find("  private:"):
		print("  ResourceAllocatorManagerD3D12.h already patched")
		return True
	if public_anchor not in content or private_decl not in content:
		print("  Error: anchors not found in ResourceAllocatorManagerD3D12.h")
		return False

	content = content.replace(private_decl, "", 1)
	content = content.replace(
		public_anchor,
		public_anchor
		+ "\n"
		+ "    // Releases every pooled heap back to the OS. Public so the\n"
		+ "    // device's ReduceMemoryUsageImpl can trim the pool at runtime\n"
		+ "    // (the Vulkan allocator's FreeRecycledMemory is public too).\n"
		+ private_decl,
		1,
	)
	header.write_text(content)
	print("  Patched ResourceAllocatorManagerD3D12.h (FreeRecycledAllocations public)")
	return True


def patch_device_header(dawn_native: Path) -> bool:
	header = dawn_native / "d3d12" / "DeviceD3D12.h"
	content = header.read_text()

	if "ReduceMemoryUsageImpl" in content:
		print("  DeviceD3D12.h already patched")
		return True

	anchor = "    MaybeError TickImpl() override;\n"
	if anchor not in content:
		print("  Error: anchor not found in DeviceD3D12.h")
		return False

	content = content.replace(
		anchor,
		anchor + "    bool ReduceMemoryUsageImpl() override;\n",
		1,
	)
	header.write_text(content)
	print("  Patched DeviceD3D12.h (ReduceMemoryUsageImpl declaration)")
	return True


def patch_device_source(dawn_native: Path) -> bool:
	source = dawn_native / "d3d12" / "DeviceD3D12.cpp"
	content = source.read_text()

	if "ReduceMemoryUsageImpl" in content:
		print("  DeviceD3D12.cpp already patched")
		return True

	anchor = "MaybeError Device::TickImpl() {\n"
	if anchor not in content:
		print("  Error: anchor not found in DeviceD3D12.cpp")
		return False

	body = (
		"bool Device::ReduceMemoryUsageImpl() {\n"
		"    // Tick the allocator so serial-deferred deletions reach the recycle\n"
		"    // pool, then release every pooled heap back to the OS. Without this\n"
		"    // the pool is unbounded and freed only at device destruction, so a\n"
		"    // long-lived device pins the committed-heap peak of every resize\n"
		"    // burst forever. Mirrors the Vulkan backend's FreeRecycledMemory()\n"
		"    // call; DeviceBase::ReduceMemoryUsage already ran CheckPassedSerials.\n"
		"    ExecutionSerial completedSerial = GetQueue()->GetCompletedCommandSerial();\n"
		"    (*mResourceAllocatorManager)->Tick(completedSerial);\n"
		"    (*mResourceAllocatorManager)->FreeRecycledAllocations();\n"
		"    return false;\n"
		"}\n"
		"\n"
	)
	content = content.replace(anchor, body + anchor, 1)
	source.write_text(content)
	print("  Patched DeviceD3D12.cpp (ReduceMemoryUsageImpl body)")
	return True


def apply_patches(skia_dir: Path) -> bool:
	dawn_native = (
		skia_dir / "third_party" / "externals" / "dawn" / "src" / "dawn" / "native"
	)
	if not dawn_native.exists():
		print(f"  Error: Dawn native sources not found: {dawn_native}")
		return False
	ok = patch_allocator_header(dawn_native)
	ok = patch_device_header(dawn_native) and ok
	ok = patch_device_source(dawn_native) and ok
	return ok


if __name__ == "__main__":
	if len(sys.argv) < 2:
		print("Usage: apply_dawn_d3d12_reduce_memory.py <skia_src_dir>")
		sys.exit(1)

	skia_dir = Path(sys.argv[1])
	if not skia_dir.exists():
		print(f"Error: Skia directory not found: {skia_dir}")
		sys.exit(1)

	print("Adding D3D12 ReduceMemoryUsageImpl (heap pool trim)...")
	if apply_patches(skia_dir):
		print("Done!")
	else:
		print("Failed to apply patches")
		sys.exit(1)
