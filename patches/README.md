# patches/ — local modifications to the vendored Skia + Dawn tree

This directory holds every local change we lay over the upstream sources
after `build-skia.py` syncs them. Read this before touching a patch, before
any Skia/Dawn milestone bump, and before trusting a freshly built library:
**a patch that silently failed to apply produces libraries missing its fix,
and the build does NOT stop when that happens.**

## How patches are applied (and the one trap)

`build-skia.py` → `apply_patches()` runs right after `sync_deps()`:

1. Every `*.patch` file (sorted) via `git apply --ignore-whitespace`, with a
   `--check --reverse` probe first so an already-applied patch is skipped.
   There are currently no `.patch` files — the mechanism stays because it
   was used before (see the retired-patches section).
2. Every `apply_*.py` script (sorted alphabetically), each invoked as
   `python <script> <skia_src_dir>`. Scripts are idempotent: they detect an
   already-patched file and report it instead of double-applying.

**The trap:** both loops catch failures and print
`Warning: Failed to ...` — the build keeps going. So on every build whose
patches matter (every milestone bump, every patch edit), check the build
log for each script's success lines before using the produced libraries.

Two more patch steps live HARDCODED in `build-skia.py` itself, outside this
directory: `patch_dawn_crt_runtime()` and `patch_angle_build_gn()`. This
directory is therefore not the complete local-modification story — grep
`build-skia.py` for `def patch_` when auditing.

## Verifying a build picked everything up

Grep the build log for these exact lines (one per patched file, plus the
script's own success line):

- `apply_dawn_d3d12_reduce_memory.py` →
  `Patched ResourceAllocatorManagerD3D12.h (FreeRecycledAllocations public)`,
  `Patched DeviceD3D12.h (ReduceMemoryUsageImpl declaration)`,
  `Patched DeviceD3D12.cpp (ReduceMemoryUsageImpl body, v2)`
  (or the corresponding `already patched` lines on a re-run).
- `apply_dawn_disable_cxx_modules.py` →
  `Patched build_dawn.py (disable dawncpp_module)` / `already patched`.
- `apply_dawn_ios_visionos.py` → `Patched args.gni`, `Patched BUILD.gn`,
  `Patched build_dawn.py`, `Patched cmake_utils.py` (Apple targets; on a
  Windows-only build these files are still patched — the edits are inert
  off-Apple).

Downstream reminder: the produced Skia/Dawn libraries feed BOTH skia-gleam
DLL flavors (normal and tracing). After changing any patch, rebuild the
libraries and then both flavors — a tracing DLL built against stale
libraries silently lacks the patch.

## The patches

### apply_dawn_d3d12_reduce_memory.py — ours, 2026-08-02 (v2 same day)

**What:** gives Dawn's D3D12 backend a working
`ReduceMemoryUsageImpl` (upstream implements one only for D3D11 and
Vulkan; the base returns false, so the call never touches the heap pool).
Edits `ResourceAllocatorManagerD3D12.h` (makes `FreeRecycledAllocations`
public, the visibility its Vulkan sibling has), `DeviceD3D12.h`
(declaration) and `DeviceD3D12.cpp` (the override: force-flush the pending
serial, tick the allocator so serial-deferred deletions reach the recycle
pool, free every pooled heap, clear the ref queue up to the completed
serial, and answer "pending work" honestly so the caller's retry contract
converges).

**Why:** the D3D12 heap pool is unbounded and its only upstream release
point is the manager's destructor — a long-lived device keeps the
committed-heap peak of every resize burst until process exit (measured
before the patch: a demo idling at 60 MB dedicated GPU pinned 837 MB after
an interactive resize). The toolkit's GPU cleanup sweeps rely on this call
actually trimming.

**Symptom if silently missing:** `DawnDevice.reduceMemoryUsage()` returns
without freeing anything; VRAM never returns after resize bursts; the
post-resize VRAM-pin behavior reappears.

**Retire when:** upstream grows its own D3D12 `ReduceMemoryUsageImpl` or
pool-trim path — crbug.com/398193014 tracks that area. Check on every
milestone bump.

### apply_dawn_disable_cxx_modules.py — ours, 2026-07-04 (m151)

**What:** pre-seeds `-DDAWN_SUPPORTS_CXX_MODULES=OFF` into Dawn's CMake
invocation (edits Dawn's `build_dawn.py`), skipping the `dawncpp_module`
C++20 module-interface target.

**Why:** with clang-cl on Windows, Dawn's compiler probe for module
support passes but CMake cannot actually scan module import graphs for
clang-cl, so the generate step fails ("the compiler does not provide a way
to discover the import graph dependencies"). Skia consumes only Dawn's
`webgpu_cpp` headers, never the module interface.

**Symptom if silently missing:** the Dawn CMake generate step fails with
the dawncpp_module import-graph error; no libraries are produced at all
(this one fails loudly downstream, unlike the others).

**Retire when:** CMake learns clang-cl module scanning, or Dawn's probe
starts detecting the CMake+clang-cl combination itself. Re-test by
removing the patch on a milestone bump and watching the generate step.

### apply_dawn_ios_visionos.py — fork origin, January 2026

**What:** teaches Dawn's GN/CMake bridge about iOS and visionOS targets:
a `dawn_target_platform` GN arg (`args.gni`), simulator/visionOS flag
plumbing (`BUILD.gn`), and the corresponding SDK selection in Dawn's
`build_dawn.py` and `cmake_utils.py` (visionOS builds ride
`target_os=ios` with the xros SDK substituted).

**Why:** inherited from this repo's fork origin, which built Skia+Dawn
for Apple platforms. GleamUI's Windows/macOS builds do not exercise it,
but the patch is kept: it is inert off-Apple, and an eventual
iOS/visionOS target would need it again.

**Symptom if silently missing:** nothing, on Windows/macOS builds. Apple
mobile builds would select the wrong SDK / miss the simulator flag.

**Retire when:** the fork's Apple-mobile support is formally dropped, or
upstream Dawn grows native visionOS target support.

## Retired patches (the precedent)

- `fix_m149_d3d_backend_surface.patch` (added 2026-06-15, dropped
  2026-08-01 with the move to m152): m149–m151 needed a GPU_TEST_UTILS
  D3D backend-surface fix that upstream m152 made unnecessary. Retirement
  looked like: milestone bump → patch anchor no longer matched → verified
  upstream contained the fix → patch deleted in the same commit as the
  default-branch bump.

## Adding a new patch — conventions a later you should keep

- Python script named `apply_<area>_<what>.py`, taking the Skia source dir
  as `argv[1]` (the build passes it automatically; scripts run in sorted
  order, alphabetical by name).
- Anchor-replace style: find an exact upstream text anchor, replace with
  anchor + insertion. A missing anchor MUST print an error and exit
  non-zero — that is what turns a milestone bump's silent drift into a
  visible (if only warning-level) build-log line.
- Idempotent: detect the already-patched state first and print
  `<file> already patched`.
- Print one `Patched <file> (<what>)` line per file, and add those exact
  lines to the verification section of this README.
- Document IN THE SCRIPT'S DOCSTRING: the mechanism, the measured symptom
  it fixes, and the retirement condition. The docstring is the primary
  record; this README is the index.
- Update this README's inventory in the same commit.
