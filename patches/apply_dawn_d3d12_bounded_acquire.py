#!/usr/bin/env python3
"""
Bound Dawn's D3D12 fence wait so a dead fence cannot park a thread forever.

d3d12::Queue::WaitForSerial waits once with an INFINITE timeout
(std::numeric_limits<Nanoseconds>::max()). Every escape from that wait is
downstream of it: the device-removal sentinel (GetCompletedValue() ==
UINT64_MAX, read by CheckAndUpdateCompletedSerials) is only consulted AFTER
the wait returns, and Queue::SetEventOnCompletion discards the HRESULT that
arms the fence event — a failed arming leaves a manual-reset event
unsignaled for the rest of the process. The wait therefore has states it
never leaves.

Measured symptom: a render thread RUNNABLE-in-native inside the swap chain's
GetCurrentTexture -> d3d12::SwapChain::GetCurrentTextureImpl ->
Queue::WaitForSerial, on a WARP-saturated run, with the window frozen and
the process otherwise healthy. The application's device-loss recovery never
engages because no error is ever produced — there is nothing to classify.
The WARP-internal trigger for the stall itself is unknown (a 15-minute
saturated control run did not reproduce it); this patch fixes the
consequence, not the trigger.

Two edits, both in src/dawn/native/d3d12/QueueD3D12.cpp:

1. WaitForSerial waits in ten one-second slices instead of once forever,
   calling CheckPassedSerials() after each slice so a removal that happens
   mid-wait surfaces as Dawn's own DAWN_DEVICE_LOST_ERROR, and returning
   early as soon as the serial completes. Exhausting the budget returns
   DAWN_INTERNAL_ERROR, which DeviceBase::HandleError promotes to a device
   loss — so the consequence of a hung fence becomes the ordinary
   lost-device signal a caller can rebuild from.

   The bound is applied to WaitForSerial itself rather than to the swap
   chain's call site because WaitForQueueSerialImpl is private in
   ExecutionQueueBase and protected in d3d::Queue: only the queue class can
   slice the wait, and doing it there needs no header change. The public
   ExecutionQueueBase::WaitForQueueSerial is deliberately NOT substituted —
   it takes the device guard on a non-thread-safe path and can fire user
   callbacks through UpdateCompletedSerial, both of which WaitForSerial
   bypasses today.

   Consequence, accepted knowingly: expiry is destructive, not
   probabilistic. Dawn's error handling flips the device to lost before the
   loss callback runs, and nothing can distinguish "this fence will never
   signal" from "a legitimately extreme wait", so anything parking the wait
   past ten seconds (a sleep/resume edge, an extreme GPU stall) costs a real
   device teardown. The trade is one recovery stutter against a permanently
   frozen window. The bound also widens to WaitForSerial's other callers
   (DetachAndWaitForDeallocation, WaitForIdleForDestructionImpl,
   OpenPendingCommands): a teardown that hangs forever on a dead fence
   becomes a device-lost error instead. That widening is intended.

2. SetEventOnCompletion checks its HRESULT and logs the failure. It cannot
   return an error (the virtual is void), so the event is still left
   unsignaled — but edit 1 now converts that into the timeout path, and the
   log line makes the today-silent proximate cause visible in a capture.

Retire when upstream bounds the wait itself or checks the arming HRESULT.
Check on every Dawn/Skia milestone bump: if the anchors stop matching,
confirm whether upstream grew either fix before re-anchoring.
"""

import sys
from pathlib import Path

QUEUE_REL_PATH = ("d3d12", "QueueD3D12.cpp")

LOG_INCLUDE_ANCHOR = '#include "src/utils/compiler.h"\n'
LOG_INCLUDE = '#include "src/utils/log.h"\n'

WAIT_ANCHOR = """MaybeError Queue::WaitForSerial(ExecutionSerial serial) {
    if (GetCompletedCommandSerial() >= serial) {
        return {};
    }
    DAWN_TRY_ASSIGN(std::ignore,
                    WaitForQueueSerialImpl(serial, std::numeric_limits<Nanoseconds>::max()));
    return CheckPassedSerials();
}
"""

WAIT_REPLACEMENT = """MaybeError Queue::WaitForSerial(ExecutionSerial serial) {
    if (GetCompletedCommandSerial() >= serial) {
        return {};
    }
    // Bounded fence wait. Waiting once with an infinite timeout makes a fence
    // that never signals a permanent park of the calling thread: the
    // device-removal sentinel (GetCompletedValue() == UINT64_MAX, read by
    // CheckAndUpdateCompletedSerials) is only reachable AFTER the wait returns,
    // and an ID3D12Fence::SetEventOnCompletion that failed to arm leaves a
    // manual-reset event unsignaled for good. Slicing the wait and calling
    // CheckPassedSerials between slices lets a device that died mid-wait
    // surface as Dawn's own device-lost error instead.
    //
    // Exhausting the whole budget is treated as a lost device on purpose.
    // Nothing here can distinguish "this fence will never signal" from "a
    // legitimately extreme wait", and a thread parked forever is the worse of
    // the two outcomes: legitimate waits are frame-pacing scale, two orders of
    // magnitude below this budget even on a software adapter. The internal
    // error is promoted to a device loss by DeviceBase::HandleError, so the
    // caller sees the ordinary lost-device signal and can rebuild.
    static constexpr uint32_t kWaitSliceCount = 10;
    static constexpr Nanoseconds kWaitSliceTimeout = Nanoseconds(uint64_t(1000000000));
    for (uint32_t slice = 0; slice < kWaitSliceCount; ++slice) {
        ExecutionSerial waited;
        DAWN_TRY_ASSIGN(waited, WaitForQueueSerialImpl(serial, kWaitSliceTimeout));
        DAWN_TRY(CheckPassedSerials());
        if (waited != kWaitSerialTimeout || GetCompletedCommandSerial() >= serial) {
            return {};
        }
    }
    return DAWN_INTERNAL_ERROR(
        "D3D12 fence wait exceeded its bounded budget; treating the device as lost.");
}
"""

EVENT_ANCHOR = """void Queue::SetEventOnCompletion(ExecutionSerial serial, HANDLE event) {
    mFence->SetEventOnCompletion(static_cast<uint64_t>(serial), event);
}
"""

EVENT_REPLACEMENT = """void Queue::SetEventOnCompletion(ExecutionSerial serial, HANDLE event) {
    // A failed arming leaves the manual-reset event unsignaled forever. The
    // virtual is void, so the failure cannot be returned - but the bounded wait
    // in WaitForSerial turns it into a timeout rather than a permanent park,
    // and this log line is what tells the two causes apart afterwards.
    HRESULT hr = mFence->SetEventOnCompletion(static_cast<uint64_t>(serial), event);
    if (FAILED(hr)) {
        dawn::ErrorLog() << "D3D12 ID3D12Fence::SetEventOnCompletion failed ("
                         << d3d::HRESULTAsString(hr) << ") for serial "
                         << uint64_t(serial) << "; the fence event will never signal.";
    }
}
"""


def read_source(path: Path) -> tuple[str, str]:
	"""Reads the file, returning ('\\n'-normalized text, the newline to write back)."""
	raw = path.read_bytes()
	newline = "\r\n" if b"\r\n" in raw else "\n"
	return raw.decode("utf-8").replace("\r\n", "\n"), newline


def write_source(path: Path, content: str, newline: str) -> None:
	path.write_bytes(content.replace("\n", newline).encode("utf-8"))


def patch_queue_source(dawn_native: Path) -> bool:
	source = dawn_native.joinpath(*QUEUE_REL_PATH)
	content, newline = read_source(source)

	already = (
		LOG_INCLUDE in content
		and WAIT_REPLACEMENT in content
		and EVENT_REPLACEMENT in content
	)
	if already:
		print("  QueueD3D12.cpp already patched")
		return True

	missing = [
		name
		for name, anchor in (
			("compiler.h include", LOG_INCLUDE_ANCHOR),
			("Queue::WaitForSerial", WAIT_ANCHOR),
			("Queue::SetEventOnCompletion", EVENT_ANCHOR),
		)
		if anchor not in content
	]
	if missing:
		print(
			"  Error: anchors not found in QueueD3D12.cpp: " + ", ".join(missing)
		)
		return False

	content = content.replace(
		LOG_INCLUDE_ANCHOR, LOG_INCLUDE_ANCHOR + LOG_INCLUDE, 1
	)
	content = content.replace(WAIT_ANCHOR, WAIT_REPLACEMENT, 1)
	content = content.replace(EVENT_ANCHOR, EVENT_REPLACEMENT, 1)
	write_source(source, content, newline)
	print(
		"  Patched QueueD3D12.cpp "
		"(bounded WaitForSerial + SetEventOnCompletion HRESULT check)"
	)
	return True


def apply_patches(skia_dir: Path) -> bool:
	dawn_native = (
		skia_dir / "third_party" / "externals" / "dawn" / "src" / "dawn" / "native"
	)
	if not dawn_native.exists():
		print(f"  Error: Dawn native sources not found: {dawn_native}")
		return False
	return patch_queue_source(dawn_native)


if __name__ == "__main__":
	if len(sys.argv) < 2:
		print("Usage: apply_dawn_d3d12_bounded_acquire.py <skia_src_dir>")
		sys.exit(1)

	skia_dir = Path(sys.argv[1])
	if not skia_dir.exists():
		print(f"Error: Skia directory not found: {skia_dir}")
		sys.exit(1)

	print("Bounding the D3D12 fence wait (swap-chain acquire park)...")
	if apply_patches(skia_dir):
		print("Done!")
	else:
		print("Failed to apply patches")
		sys.exit(1)
