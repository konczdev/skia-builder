/**
 * Metal surface helper for macOS
 * This file provides Objective-C++ functions to create Metal layers from GLFW windows.
 */

#include "metal_surface_helper.h"

#import <Cocoa/Cocoa.h>
#import <QuartzCore/CAMetalLayer.h>

void* createMetalLayerForWindow(void* cocoaWindow) {
    NSWindow* nsWindow = (__bridge NSWindow*)cocoaWindow;
    if (!nsWindow) {
        return nullptr;
    }

    NSView* contentView = [nsWindow contentView];
    if (!contentView) {
        return nullptr;
    }

    [contentView setWantsLayer:YES];
    CAMetalLayer* metalLayer = [CAMetalLayer layer];
    [contentView setLayer:metalLayer];

    return (__bridge void*)metalLayer;
}
