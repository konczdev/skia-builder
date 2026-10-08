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

- `apply_dawn_d3d12_bounded_acquire.py` →
  `Patched QueueD3D12.cpp (bounded WaitForSerial + SetEventOnCompletion HRESULT check)`
  (or `QueueD3D12.cpp already patched` on a re-run).
- `apply_dawn_d3d12_reduce_memory.py` →
  `Patched ResourceAllocatorManagerD3D12.h (FreeRecycledAllocations public)`,
  `Patched DeviceD3D12.h (ReduceMemoryUsageImpl declaration)`,
  `Patched DeviceD3D12.cpp (ReduceMemoryUsageImpl body, v2)`
  (or the corresponding `already patched` lines on a re-run).
- `apply_dawn_disable_cxx_modules.py` →
  `Patched build_dawn.py (disable dawncpp_module)` / `already patched`.
- `apply_dawn_dxc_option.py` →
  `Patched args.gni (dawn_enable_dxc)`, `Patched BUILD.gn (dawn_enable_dxc)`,
  `Patched build_dawn.py (dawn_enable_dxc)` (or `already patched
  (dawn_enable_dxc)` per file on a re-run). On a Windows build, also check
  that the tmp dir's `cmake_dawn/CMakeCache.txt` carries
  `-DDAWN_USE_BUILT_DXC` in `CMAKE_CXX_FLAGS` while
  `DAWN_USE_BUILT_DXC:BOOL` stays `OFF` (the define without the source
  build).
- `apply_dawn_ios_visionos.py` → `Patched args.gni`, `Patched BUILD.gn`,
  `Patched build_dawn.py`, `Patched cmake_utils.py` (Apple targets; on a
  Windows-only build these files are still patched — the edits are inert
  off-Apple).
- `apply_skia_graphite_deferred_canvas_props.py` →
  `Patched Recorder.h (makeDeferredCanvas with SkSurfaceProps)`,
  `Patched Recorder.cpp (makeDeferredCanvas with SkSurfaceProps)` (or the
  `already patched` forms on a re-run). A Skia without it fails loudly
  downstream: skia-gleam's `skg_recorder_make_deferred_canvas` calls the
  three-argument overload and does not compile against an unpatched header.

Downstream reminder: the produced Skia/Dawn libraries feed EVERY skia-gleam
DLL flavor (normal and tracing). After changing
any patch, rebuild the libraries of each flavor in use and then those
DLLs — a flavor DLL built against stale libraries silently lacks the
patch.

## The patches

### apply_dawn_d3d12_bounded_acquire.py — ours, 2026-08-14

**What:** bounds `d3d12::Queue::WaitForSerial` — ten one-second slices with
a `CheckPassedSerials()` between them, an early return the moment the serial
completes, and `DAWN_INTERNAL_ERROR` when the whole budget expires — and
makes `Queue::SetEventOnCompletion` check and log the HRESULT it used to
discard. One file: `QueueD3D12.cpp`.

**Why:** upstream waits once with an infinite timeout, and every escape from
that wait sits downstream of it. The device-removal sentinel
(`GetCompletedValue() == UINT64_MAX`) is only read after the wait returns,
and an arming call that failed leaves a manual-reset event unsignaled for
the rest of the process — so the wait has states it never leaves. Measured:
a render thread RUNNABLE-in-native inside the swap chain's
`GetCurrentTexture` on a WARP-saturated run, window frozen, no error ever
produced and therefore nothing for device-loss recovery to classify. The
budget expiry is deliberately destructive: `DeviceBase::HandleError`
promotes the internal error to a device loss, which turns a permanent park
into one recovery stutter. The bound also reaches `WaitForSerial`'s other
callers (`DetachAndWaitForDeallocation`, `WaitForIdleForDestructionImpl`,
`OpenPendingCommands`), so a teardown that would hang forever on a dead
fence becomes a device-lost error instead — intended.

**Symptom if silently missing:** a wedged fence parks the calling thread
forever again; on the render worker that is a frozen window with a live
process, and no classification, no recovery, and no log line anywhere.

**Retire when:** upstream bounds the wait itself or checks the arming
HRESULT. Check on every milestone bump — if the anchors stop matching,
confirm whether upstream grew either fix before re-anchoring.

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

### apply_dawn_dxc_option.py — ours, 2026-10-07

**What:** adds a `dawn_enable_dxc` GN arg (Skia's `third_party/dawn`
`args.gni`, default `is_win`), passes it to Skia's Dawn bridge (`BUILD.gn`),
and there appends `-DDAWN_USE_BUILT_DXC` to Dawn's C/C++ flags on Windows
(`build_dawn.py`). The arg defaults to `is_win`, so every Windows build
carries the DXC path; other platforms never build the D3D12 backend.

**Why:** Dawn compiles every line of its D3D12 DXC path, and the D3D12
features that need shader model 6 (ShaderF16, Subgroups,
SubgroupSizeControl, AtomicVec2uMinMax), only under that macro, and
defines it only together with building DXC from source. Dawn never links
DXC: it opens `dxcompiler.dll` at device creation, and the DXC types come
from the Windows SDK's `dxcapi.h`, which every build already includes. The
define alone therefore gives a Dawn whose `use_dxc` toggle selects DXC or
FXC at runtime. Measured on the warmup thread of a serial pipeline warmup
(RTX 5060 Ti, warm driver cache): FXC took 92.5% of its 17 s.

**Symptom if silently missing:** a Windows build is an FXC-only build
again: skia-gleam devices report FXC under the automatic choice, and a
device that requires DXC refuses to be created.

**Retire when:** Skia's Dawn bridge grows its own DXC option, or GleamUI
stops shipping the D3D12 backend.

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

### apply_skia_graphite_deferred_canvas_props.py — ours, 2026-10-08

**What:** adds `Recorder::makeDeferredCanvas(const SkImageInfo&, const
TextureInfo&, const SkSurfaceProps&)` and passes the properties to the
deferred canvas's device; the two-argument form forwards with
`SkSurfaceProps()`, so it behaves exactly as before. Two files:
`include/gpu/graphite/Recorder.h` and `src/gpu/graphite/Recorder.cpp`. The
only patch here that changes Skia itself rather than Dawn or the build.

**Why:** a deferred canvas records into a texture that a surface supplies
when the recording is inserted, and upstream makes its device with default
surface properties, which the caller cannot change. Its text then takes
Skia's stock contrast, gamma and pixel geometry instead of those of the
surface it lands on. GleamUI draws a heavy frame on several threads, each
into a deferred canvas whose recording the render thread inserts into the
window's scene texture in paint order; with default properties 27,816
pixels of MotionMark's Design frame differed from drawing it directly (up
to 5 levels, all text), with the scene's none (gleamui-measurements
`render-perf/2026-10-08-deferred-slices`).

**Symptom if silently missing:** skia-gleam does not compile (it calls the
new overload). Were skia-gleam changed back to the old call, text drawn in
GleamUI's slices would differ slightly from the rest of the window.

**Retire when:** upstream lets a deferred canvas take surface properties.
Check on every milestone bump.

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
