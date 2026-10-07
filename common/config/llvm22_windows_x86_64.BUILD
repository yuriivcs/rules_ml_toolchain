# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

load(
    "@rules_ml_toolchain//third_party/rules_cc_toolchain/features:cc_toolchain_import.bzl",
    "cc_toolchain_import",
)

exports_files(glob(["bin/*"]))

CLANG_VERSION = "22"

filegroup(
    name = "all",
    srcs = glob(["**/*"]),
    visibility = ["//visibility:public"],
)

filegroup(
    name = "clang",
    srcs = glob(
        ["bin/clang.exe"],
        allow_empty = True,
    ),
    visibility = ["//visibility:public"],
)

filegroup(
    name = "clang++",
    srcs = glob(
        ["bin/clang++.exe"],
        allow_empty = True,
    ),
    visibility = ["//visibility:public"],
)

filegroup(
    name = "ar",
    srcs = ["bin/llvm-ar.exe"],
    visibility = ["//visibility:public"],
)

filegroup(
    name = "lld",
    srcs = glob(
        [
            "bin/lld-link.exe",
            "bin/lld.exe",
        ],
        allow_empty = True,
    ),
    visibility = ["//visibility:public"],
)

filegroup(
    name = "distro_libs",
    srcs = glob(
        ["bin/*.dll"],
        allow_empty = True,
    ),
    visibility = ["//visibility:public"],
)

cc_toolchain_import(
    name = "compiler_incs",
    hdrs = glob(
        [
            "lib/clang/*/*.h",
            "lib/clang/*/include/*.h",
            "lib/clang/*/include/**/*.h",
        ],
        allow_empty = True,
    ),
    includes = [
        "lib/clang/{clang_version}".format(clang_version = CLANG_VERSION),
        "lib/clang/{clang_version}/include".format(clang_version = CLANG_VERSION),
    ],
    visibility = ["//visibility:public"],
)

cc_toolchain_import(
    name = "libclang_rt",
    additional_libs = glob(
        ["lib/clang/{clang_version}/lib/*/clang_rt.builtins-*.lib".format(clang_version = CLANG_VERSION)],
        allow_empty = True,
    ),
    visibility = ["//visibility:public"],
)

#============================================================================================
# Fortran

filegroup(
    name = "flang",
    srcs = glob(
        [
            "bin/flang.exe",
            "bin/flang-new.exe",
        ],
        allow_empty = True,
    ),
    visibility = ["//visibility:public"],
)

cc_toolchain_import(
    name = "flang_incs",
    hdrs = glob(
        ["include/flang/**"],
        allow_empty = True,
    ),
    includes = [
        "include/flang",
    ],
    visibility = ["//visibility:public"],
)

cc_toolchain_import(
    name = "fortran_libs",
    additional_libs = glob(
        [
            "lib/FortranRuntime*.lib",
            "lib/FortranDecimal*.lib",
            "lib/clang/{clang_version}/lib/*/flang_rt.runtime.static.lib".format(clang_version = CLANG_VERSION),
            "lib/clang/{clang_version}/lib/*/clang_rt.builtins-*.lib".format(clang_version = CLANG_VERSION),
        ],
        allow_empty = True,
    ),
    visibility = ["//visibility:public"],
)

filegroup(
    name = "fortran_main",
    srcs = glob(
        ["lib/Fortran_main*.lib"],
        allow_empty = True,
    ),
    visibility = ["//visibility:public"],
)
