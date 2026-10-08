#!/usr/bin/env python3
"""
Give Graphite's deferred canvas the surface properties of the surface it will
draw into.

skgpu::graphite::Recorder::makeDeferredCanvas(const SkImageInfo&,
const TextureInfo&) records into a lazy texture proxy that a surface
instantiates when the Recording is inserted (InsertRecordingInfo's
fTargetSurface). Its device is made with default SkSurfaceProps
(Recorder.cpp: Device::Make(..., {}, LoadOp::kLoad)), and the caller has no
way to pass others. Text drawn through such a canvas therefore takes Skia's
stock text contrast, gamma and pixel geometry, not those of the surface it
lands on.

GleamUI draws one frame on several threads: each worker records a run of the
frame's drawing into a deferred canvas, and the render thread inserts the
recordings in paint order with the window's scene texture as their target.
Measured (gleamui-measurements render-perf/2026-10-08-deferred-slices): with
the default properties 27,816 pixels of MotionMark's Design frame differ from
drawing it directly, by up to 5 levels, all of them text; with the text
prepared under the scene's properties no pixel differs.

The patch adds an overload taking const SkSurfaceProps& and passes it to the
device; the two-argument form forwards with SkSurfaceProps(), so it behaves
exactly as before. Two files: include/gpu/graphite/Recorder.h (the
declaration) and src/gpu/graphite/Recorder.cpp (the definition). Each keeps
its own line endings (a Windows checkout has CRLF).

Retire when: upstream lets a deferred canvas take surface properties. Check
on every milestone bump; if the anchors stop matching, look whether upstream
grew the parameter before re-anchoring.
"""

import sys
from pathlib import Path


HEADER_ANCHOR = (
	"    SkCanvas* makeDeferredCanvas(const SkImageInfo&, const TextureInfo&);\n"
)
HEADER_ADDITION = (
	"    // The same, with the surface properties the canvas's device draws with (text contrast and\n"
	"    // gamma, pixel geometry), so that its drawing matches a surface made with those properties.\n"
	"    // The form above uses the default properties. Added by skia-builder's\n"
	"    // patches/apply_skia_graphite_deferred_canvas_props.py.\n"
	"    SkCanvas* makeDeferredCanvas(const SkImageInfo&, const TextureInfo&, const SkSurfaceProps&);\n"
)
HEADER_MARKER = "makeDeferredCanvas(const SkImageInfo&, const TextureInfo&, const SkSurfaceProps&);"

SOURCE_SIGNATURE_ANCHOR = (
	"SkCanvas* Recorder::makeDeferredCanvas(const SkImageInfo& imageInfo,\n"
	"                                       const TextureInfo& textureInfo) {\n"
)
SOURCE_SIGNATURE_REPLACEMENT = (
	"SkCanvas* Recorder::makeDeferredCanvas(const SkImageInfo& imageInfo,\n"
	"                                       const TextureInfo& textureInfo) {\n"
	"    return this->makeDeferredCanvas(imageInfo, textureInfo, SkSurfaceProps());\n"
	"}\n"
	"\n"
	"SkCanvas* Recorder::makeDeferredCanvas(const SkImageInfo& imageInfo,\n"
	"                                       const TextureInfo& textureInfo,\n"
	"                                       const SkSurfaceProps& props) {\n"
)
SOURCE_DEVICE_ANCHOR = (
	"    fTargetProxyDevice = Device::Make(this,\n"
	"                                      fTargetProxyData->refLazyProxy(),\n"
	"                                      imageInfo.dimensions(),\n"
	"                                      imageInfo.colorInfo(),\n"
	"                                      {},\n"
	"                                      LoadOp::kLoad);\n"
)
SOURCE_DEVICE_REPLACEMENT = (
	"    fTargetProxyDevice = Device::Make(this,\n"
	"                                      fTargetProxyData->refLazyProxy(),\n"
	"                                      imageInfo.dimensions(),\n"
	"                                      imageInfo.colorInfo(),\n"
	"                                      props,\n"
	"                                      LoadOp::kLoad);\n"
)
SOURCE_MARKER = "                                       const SkSurfaceProps& props) {\n"


def read(path: Path) -> tuple[str, str]:
	"""Returns a file's text and its line ending."""
	content = path.read_bytes().decode("utf-8")
	return content, "\r\n" if "\r\n" in content else "\n"


def write(path: Path, content: str) -> None:
	# Bytes out, so that Python adds no line-ending translation of its own.
	path.write_bytes(content.encode("utf-8"))


def lines(text: str, ending: str) -> str:
	"""Gives an anchor or an insertion the file's line ending."""
	return text.replace("\n", ending)


def patch_header(skia_dir: Path) -> bool:
	header = skia_dir / "include" / "gpu" / "graphite" / "Recorder.h"
	content, ending = read(header)
	if HEADER_MARKER in content:
		print("  Recorder.h already patched (makeDeferredCanvas with SkSurfaceProps)")
		return True
	anchor = lines(HEADER_ANCHOR, ending)
	if content.count(anchor) != 1:
		print("  Error: makeDeferredCanvas declaration anchor not found once in Recorder.h")
		return False
	write(header, content.replace(anchor, anchor + lines(HEADER_ADDITION, ending)))
	print("  Patched Recorder.h (makeDeferredCanvas with SkSurfaceProps)")
	return True


def patch_source(skia_dir: Path) -> bool:
	source = skia_dir / "src" / "gpu" / "graphite" / "Recorder.cpp"
	content, ending = read(source)
	if lines(SOURCE_MARKER, ending) in content:
		print("  Recorder.cpp already patched (makeDeferredCanvas with SkSurfaceProps)")
		return True
	signature = lines(SOURCE_SIGNATURE_ANCHOR, ending)
	device = lines(SOURCE_DEVICE_ANCHOR, ending)
	if content.count(signature) != 1:
		print("  Error: makeDeferredCanvas definition anchor not found once in Recorder.cpp")
		return False
	if content.count(device) != 1:
		print("  Error: deferred Device::Make anchor not found once in Recorder.cpp")
		return False
	content = content.replace(signature, lines(SOURCE_SIGNATURE_REPLACEMENT, ending))
	content = content.replace(device, lines(SOURCE_DEVICE_REPLACEMENT, ending))
	write(source, content)
	print("  Patched Recorder.cpp (makeDeferredCanvas with SkSurfaceProps)")
	return True


def apply_patches(skia_dir: Path) -> bool:
	# The definition needs the declaration, so the source is patched only
	# after the header.
	return patch_header(skia_dir) and patch_source(skia_dir)


if __name__ == "__main__":
	if len(sys.argv) < 2:
		print("Usage: apply_skia_graphite_deferred_canvas_props.py <skia_src_dir>")
		sys.exit(1)

	skia_dir = Path(sys.argv[1])
	if not skia_dir.exists():
		print(f"Error: Skia directory not found: {skia_dir}")
		sys.exit(1)

	print("Giving Graphite's deferred canvas surface properties...")
	if apply_patches(skia_dir):
		print("Done!")
	else:
		print("Failed to apply patches")
		sys.exit(1)
