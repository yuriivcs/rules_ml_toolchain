#=====================================================================
# Not ManyLinux tag compliant libraries for usage in deps attribute
#=====================================================================

load(":collect_cc_libraries.bzl", "collect_cc_libraries")
load("@bazel_skylib//rules:common_settings.bzl", "bool_flag")

# Export template file for local_sysroot_configure repository rule
exports_files(["defs.bzl.tpl"])

# Flag to control whether to use local (system) sysroot instead of hermetic
bool_flag(
    name = "use_local_sysroot",
    build_setting_default = False,
    visibility = ["//visibility:public"],
)

config_setting(
    name = "local_sysroot_enabled",
    flag_values = {":use_local_sysroot": "True"},
    visibility = ["//visibility:public"],
)

alias(
    name = "openmp",
    actual = select({
        "//common:is_linux_x86_64": "@sysroot_linux_x86_64//:openmp_import",
        "//common:is_linux_aarch64": "@sysroot_linux_aarch64//:openmp_import",
    }),
    visibility = ["//visibility:public"],
)

alias(
    name = "openmp_copyright",
    actual = select({
        "//common:is_linux_x86_64": "@sysroot_linux_x86_64//:openmp_copyright",
        "//common:is_linux_aarch64": "@sysroot_linux_aarch64//:openmp_copyright",
    }),
)

collect_cc_libraries(
    name = "openmp_libs",
    deps = [
        ":openmp",
        ":openmp_copyright",
    ],
    visibility = ["//visibility:public"],
)

alias(
    name = "libgcc_so",
    actual = select({
        "@bazel_tools//src/conditions:linux_x86_64": "@sysroot_linux_x86_64//:libgcc_so",
        "@bazel_tools//src/conditions:linux_aarch64": "@sysroot_linux_aarch64//:libgcc_so",
        "//conditions:default": ":empty",
    }),
    visibility = ["//visibility:public"],
)

alias(
    name = "libstdcxx_so",
    actual = select({
        "@bazel_tools//src/conditions:linux_x86_64": "@sysroot_linux_x86_64//:libstdcxx_so",
        "@bazel_tools//src/conditions:linux_aarch64": "@sysroot_linux_aarch64//:libstdcxx_so",
        "//conditions:default": ":empty",
    }),
    visibility = ["//visibility:public"],
)

alias(
    name = "libdl_so",
    actual = select({
        "@bazel_tools//src/conditions:linux_x86_64": "@sysroot_linux_x86_64//:libdl_so",
        "@bazel_tools//src/conditions:linux_aarch64": "@sysroot_linux_aarch64//:libdl_so",
        "//conditions:default": ":empty",
    }),
    visibility = ["//visibility:public"],
)

alias(
    name = "ld_linux_so",
    actual = select({
        "@bazel_tools//src/conditions:linux_x86_64": "@sysroot_linux_x86_64//:ld_linux_so",
        "@bazel_tools//src/conditions:linux_aarch64": "@sysroot_linux_aarch64//:ld_linux_so",
        "//conditions:default": ":empty",
    }),
    visibility = ["//visibility:public"],
)

alias(
    name = "libm_so",
    actual = select({
        "@bazel_tools//src/conditions:linux_x86_64": "@sysroot_linux_x86_64//:libm_so",
        "@bazel_tools//src/conditions:linux_aarch64": "@sysroot_linux_aarch64//:libm_so",
        "//conditions:default": ":empty",
    }),
    visibility = ["//visibility:public"],
)

alias(
    name = "libpthread_so",
    actual = select({
        "@bazel_tools//src/conditions:linux_x86_64": "@sysroot_linux_x86_64//:libpthread_so",
        "@bazel_tools//src/conditions:linux_aarch64": "@sysroot_linux_aarch64//:libpthread_so",
        "//conditions:default": ":empty",
    }),
    visibility = ["//visibility:public"],
)

alias(
    name = "libc_so",
    actual = select({
        "@bazel_tools//src/conditions:linux_x86_64": "@sysroot_linux_x86_64//:libc_so",
        "@bazel_tools//src/conditions:linux_aarch64": "@sysroot_linux_aarch64//:libc_so",
        "//conditions:default": ":empty",
    }),
    visibility = ["//visibility:public"],
)
