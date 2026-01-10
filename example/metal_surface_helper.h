/**
 * Metal surface helper for macOS
 * This header provides C++ callable functions for Metal layer creation.
 */

#ifndef METAL_SURFACE_HELPER_H
#define METAL_SURFACE_HELPER_H

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Creates a CAMetalLayer for the given Cocoa window.
 * @param cocoaWindow A void* to an NSWindow* (from glfwGetCocoaWindow)
 * @return A void* to a CAMetalLayer*, or nullptr on failure
 */
void* createMetalLayerForWindow(void* cocoaWindow);

#ifdef __cplusplus
}
#endif

#endif // METAL_SURFACE_HELPER_H
