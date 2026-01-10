cmake_minimum_required(VERSION 3.10)
project(SkiaTest)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Build options
option(USE_NATIVE_GRAPHITE "Build with native Graphite/Dawn support" OFF)

# Platform-specific settings
if(EMSCRIPTEN)
    # Emscripten-specific settings
    set(CMAKE_EXECUTABLE_SUFFIX ".html")
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -DSK_TRIVIAL_ABI=[[clang::trivial_abi]]")
    set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS}")

elseif(WIN32)
    # Windows-specific settings
    if(CMAKE_BUILD_TYPE STREQUAL "Debug")
        set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreadedDebug")
        set(CMAKE_CXX_FLAGS_DEBUG "${CMAKE_CXX_FLAGS_DEBUG} /MTd")
    else()
        set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded")
        set(CMAKE_CXX_FLAGS_RELEASE "${CMAKE_CXX_FLAGS_RELEASE} /MT")
    endif()
    
    if(CMAKE_GENERATOR_PLATFORM STREQUAL "x64")
        set(ARCH_DIR "x64")
    else()
        set(ARCH_DIR "Win32")
    endif()
    
elseif(APPLE)
    # macOS-specific settings
    set(CMAKE_MACOSX_RPATH 1)
    set(CMAKE_BUILD_WITH_INSTALL_RPATH TRUE)
else()
    # Linux-specific settings
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -fPIC")
endif()

# Enable Link Time Optimization if supported and not using Emscripten
if(NOT EMSCRIPTEN)
    include(CheckIPOSupported)
    check_ipo_supported(RESULT supported OUTPUT error)
    if(supported)
        set(CMAKE_INTERPROCEDURAL_OPTIMIZATION TRUE)
    else()
        message(STATUS "IPO is not supported: ${error}")
    endif()
endif()

# Set include and library directories
set(INCLUDE_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../build/include)

# Configure library paths based on platform and configuration
# Use gpu variant for native graphite, otherwise use default paths
if(USE_NATIVE_GRAPHITE)
    set(VARIANT_SUFFIX "-gpu")
else()
    set(VARIANT_SUFFIX "-gpu")  # Default to GPU variant
endif()

if(EMSCRIPTEN)
    set(LIB_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../build/wasm${VARIANT_SUFFIX}/lib/${CMAKE_BUILD_TYPE})
    set(SKIA_LIB ${LIB_DIR}/libskia.a)
elseif(WIN32)
    set(LIB_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../build/win${VARIANT_SUFFIX}/lib/${CMAKE_BUILD_TYPE}/${ARCH_DIR})
    find_library(SKIA_LIB skia PATHS ${LIB_DIR} NO_DEFAULT_PATH REQUIRED)

    if(NOT SKIA_LIB)
        message(FATAL_ERROR "Could not find Skia library in ${LIB_DIR}")
    endif()

    if(USE_NATIVE_GRAPHITE)
        find_library(DAWN_LIB dawn_combined PATHS ${LIB_DIR} NO_DEFAULT_PATH)
    endif()
elseif(APPLE)
    set(LIB_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../build/mac${VARIANT_SUFFIX}/lib/${CMAKE_BUILD_TYPE})
    find_library(SKIA_LIB skia PATHS ${LIB_DIR} NO_DEFAULT_PATH REQUIRED)

    if(USE_NATIVE_GRAPHITE)
        find_library(DAWN_LIB dawn_combined PATHS ${LIB_DIR} NO_DEFAULT_PATH)
    endif()
else()
    # Linux - detect architecture
    if(CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64|arm64")
        set(LINUX_ARCH "arm64")
    else()
        set(LINUX_ARCH "x64")
    endif()
    set(LIB_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../build/linux${VARIANT_SUFFIX}/lib/${CMAKE_BUILD_TYPE}/${LINUX_ARCH})
    find_library(SKIA_LIB skia PATHS ${LIB_DIR} NO_DEFAULT_PATH REQUIRED)

    if(USE_NATIVE_GRAPHITE)
        find_library(DAWN_LIB dawn_combined PATHS ${LIB_DIR} NO_DEFAULT_PATH)
    endif()
endif()

message(STATUS "Build Type: ${CMAKE_BUILD_TYPE}")
message(STATUS "LIB_DIR absolute path: ${LIB_DIR}")
message(STATUS "SKIA_LIB path: ${SKIA_LIB}")
if(USE_NATIVE_GRAPHITE)
    message(STATUS "DAWN_LIB path: ${DAWN_LIB}")
endif()

include_directories(${INCLUDE_DIR})

# Add Dawn include directories for native Graphite
if(USE_NATIVE_GRAPHITE)
    set(DAWN_INCLUDE_DIR ${INCLUDE_DIR}/third_party/externals/dawn/include)
    include_directories(${DAWN_INCLUDE_DIR})
    message(STATUS "Dawn include dir: ${DAWN_INCLUDE_DIR}")
endif()

# Find GLFW for native Graphite builds
if(USE_NATIVE_GRAPHITE AND NOT EMSCRIPTEN)
    find_package(glfw3 3.3 REQUIRED)
    message(STATUS "Found GLFW: ${glfw3_DIR}")
endif()

# Select source file based on build variant
if(USE_NATIVE_GRAPHITE AND NOT EMSCRIPTEN)
    if(APPLE)
        # macOS needs the Objective-C++ helper for Metal layer creation
        add_executable(example
            main-native-graphite.cpp
            metal_surface_helper.mm
        )
    else()
        add_executable(example main-native-graphite.cpp)
    endif()
    message(STATUS "Building with native Graphite/Dawn support")

    # Add Graphite compile definitions
    target_compile_definitions(example PRIVATE
        SK_GRAPHITE
        SK_DAWN
    )
else()
    add_executable(example main.cpp)
    message(STATUS "Building CPU-only example")
endif()

# Link libraries
target_link_libraries(example ${SKIA_LIB})

# Platform-specific linking
if(EMSCRIPTEN)
    target_link_options(example PRIVATE
        "-sALLOW_MEMORY_GROWTH=1"
        "-sNODEJS_CATCH_EXIT=0"
        "-sDYNAMIC_EXECUTION=0"
        "-sEXPORTED_FUNCTIONS=['_malloc','_free','_main']"
        "-sNO_EXIT_RUNTIME=1"
        "-sINITIAL_MEMORY=128MB"
        "-sWASM=1"
        "-sSTRICT=1"
        "-f wasm-exceptions"
        "-sERROR_ON_UNDEFINED_SYMBOLS=0"
        "-sFORCE_FILESYSTEM=1"
        "-sEXPORTED_RUNTIME_METHODS=['FS','ccall','cwrap']"
        "--shell-file=${CMAKE_CURRENT_SOURCE_DIR}/shell.html"
    )
elseif(APPLE)
    if(USE_NATIVE_GRAPHITE)
        # Native Graphite on macOS needs Metal framework and GLFW
        target_link_libraries(example
            ${DAWN_LIB}
            glfw
            "-framework Metal"
            "-framework QuartzCore"
            "-framework Cocoa"
            "-framework IOKit"
            "-framework IOSurface"
            "-framework CoreFoundation"
            "-framework CoreText"
            "-framework CoreGraphics"
        )
    else()
        target_link_libraries(example
            "-framework CoreFoundation"
            "-framework CoreText"
            "-framework CoreGraphics"
        )
    endif()
elseif(UNIX AND NOT APPLE)
    if(USE_NATIVE_GRAPHITE)
        # Native Graphite on Linux needs Vulkan, X11 libs, and GLFW
        find_package(Vulkan REQUIRED)

        target_link_libraries(example
            ${DAWN_LIB}
            glfw
            Vulkan::Vulkan
            X11
            X11-xcb
            pthread
            dl
        )
    else()
        target_link_libraries(example
            pthread
            dl
        )
    endif()
elseif(WIN32)
    if(USE_NATIVE_GRAPHITE)
        # Native Graphite on Windows needs D3D12/Vulkan and GLFW
        target_link_libraries(example
            ${DAWN_LIB}
            glfw
            d3d12
            dxgi
            dxguid
        )
    endif()
endif()
