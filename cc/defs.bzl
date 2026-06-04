"""Custom Starlark wrappers for C++ rules."""

load("@rules_cc//cc:defs.bzl",
    _cc_binary = "cc_binary",
    _cc_import= "cc_import",
    _cc_library = "cc_library",
    _cc_test = "cc_test",
)

def cc_binary(name, linkopts = [], **kwargs):
    """A wrapper around cc_binary.

    Args:
        name: The name of the target.
        linkopts: A list of linker options.
        **kwargs: Any standard cc_binary attributes.
    """
    # TODO: Replace sysroot by dynamic value
    _cc_binary(
        name = name,
        data = [
            "@sysroot_linux_x86_64//:sys_libs",
        ],
        linkopts = [
            "-Wl,--dynamic-linker=external/sysroot_linux_x86_64_glibc_2_39/lib64/ld-linux-x86-64.so.2",
            "-Wl,-rpath,$$ORIGIN/" + name + ".runfiles/sysroot_linux_x86_64_glibc_2_39/lib64",
            "-Wl,-rpath,$$ORIGIN/" + name + ".runfiles/sysroot_linux_x86_64_glibc_2_39/lib/x86_64-linux-gnu",
            "-Wl,-rpath,$$ORIGIN/" + name + ".runfiles/sysroot_linux_x86_64_glibc_2_39/usr/lib/x86_64-linux-gnu",
        ] + linkopts,
        **kwargs,
    )

def cc_import(name, **kwargs):
    """A wrapper around cc_import.

    Args:
        name: The name of the target.
        **kwargs: Any standard cc_import attributes (srcs, hdrs, deps, etc.).
    """
    _cc_import(
        name = name,
        **kwargs
    )

def cc_library(name, **kwargs):
    """A wrapper around cc_library.

    Args:
        name: The name of the target.
        **kwargs: Any standard cc_library attributes (srcs, hdrs, deps, etc.).
    """
    _cc_library(
        name = name,
        **kwargs
    )

def cc_test(name, linkopts = [], **kwargs):
    """A wrapper around cc_test.

    Args:
        name: The name of the target.
        linkopts: A list of linker options.
        **kwargs: Any standard cc_test attributes.
    """
    # TODO: Replace sysroot by dynamic value
    _cc_test(
        name = name,
        data = [
            "@sysroot_linux_x86_64//:sys_libs",
        ],
        linkopts = [
            "-Wl,--dynamic-linker=external/sysroot_linux_x86_64_glibc_2_39/lib64/ld-linux-x86-64.so.2",
            "-Wl,-rpath,$$ORIGIN/" + name + ".runfiles/sysroot_linux_x86_64_glibc_2_39/lib64",
            "-Wl,-rpath,$$ORIGIN/" + name + ".runfiles/sysroot_linux_x86_64_glibc_2_39/lib/x86_64-linux-gnu",
            "-Wl,-rpath,$$ORIGIN/" + name + ".runfiles/sysroot_linux_x86_64_glibc_2_39/usr/lib/x86_64-linux-gnu",
        ] + linkopts,
        **kwargs,
    )