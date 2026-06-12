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
    "@rules_cc//cc:action_names.bzl",
    "ACTION_NAMES",
    "ACTION_NAME_GROUPS",
    "ALL_CC_COMPILE_ACTION_NAMES",
    "ALL_CC_LINK_ACTION_NAMES",
    "ALL_CPP_COMPILE_ACTION_NAMES",
    "CC_LINK_EXECUTABLE_ACTION_NAMES",
    "DYNAMIC_LIBRARY_LINK_ACTION_NAMES",
)
load(
    "@rules_cc//cc:cc_toolchain_config_lib.bzl",
    "FeatureInfo",
    "env_entry",
    "env_set",
    "feature",
    "flag_group",
    "flag_set",
    "with_feature_set",
    _feature = "feature",
)

load("//cc/sysroots:sysroot_vars.bzl", "SysrootVarsInfo")

load(
    "@rules_ml_toolchain//third_party/rules_cc_toolchain/features:cc_toolchain_import.bzl",
    "CcToolchainImportInfo",
)

def _file_to_library_flag(file, static_libs):
    lib_prefix = "lib"
    if file.basename.startswith(lib_prefix):
        library_name = file.basename.replace("." + file.extension, "")
        library_flag = "-l" + library_name[len(lib_prefix):]
    else:
        library_flag = file.path

    if library_flag in static_libs:
        library_flag = "-Wl,-Bstatic " + library_flag + " -Wl,-Bdynamic"

    return library_flag

LIB_EXCLUDE_CRT_OBJS = ["crt1.o", "Scrt1.o", "gcrt1.o", "Mcrt1.o"]

def _filter_for_shared_obj(flags):
    libFlags = []
    for flag in flags:
        needed = True
        for crtObj in LIB_EXCLUDE_CRT_OBJS:
            if crtObj in flag:
                needed = False
                break

        if needed:
            libFlags.append(flag)

    return libFlags

def _get_libraries_to_link_flags():
    return [flag_set(
        actions = [
            ACTION_NAMES.cpp_link_executable,
            ACTION_NAMES.cpp_link_dynamic_library,
            ACTION_NAMES.cpp_link_nodeps_dynamic_library,
        ],
        flag_groups = [
            flag_group(
                iterate_over = "libraries_to_link",
                flags = ["%{libraries_to_link.name}"],
                expand_if_available = "libraries_to_link",
            ),
        ])]

def _get_runtime_library_search_directories_flags():
    return [flag_set(
        actions = [
            ACTION_NAMES.cpp_link_executable,
            ACTION_NAMES.cpp_link_dynamic_library,
            ACTION_NAMES.cpp_link_nodeps_dynamic_library,
            ACTION_NAMES.lto_index_for_executable,
            ACTION_NAMES.lto_index_for_dynamic_library,
            ACTION_NAMES.lto_index_for_nodeps_dynamic_library,
        ],
        flag_groups = [
            flag_group(
                iterate_over = "runtime_library_search_directories",
                flag_groups = [
                    flag_group(
                        flags = [
                            "-Wl,-rpath,$EXEC_ORIGIN/%{runtime_library_search_directories}",
                        ],
                        expand_if_true = "is_cc_test",
                    ),
                    flag_group(
                        flags = [
                            "-Wl,-rpath,$ORIGIN/%{runtime_library_search_directories}",
                        ],
                        expand_if_false = "is_cc_test",
                    ),
                ],
                expand_if_available =
                    "runtime_library_search_directories",
            ),
        ],
        with_features = [
            with_feature_set(
                features = ["static_link_cpp_runtimes"],
                not_features = ["no_solib_rpaths"],
            ),
        ],
    ),
    flag_set(
        actions = [
            ACTION_NAMES.cpp_link_executable,
            ACTION_NAMES.cpp_link_dynamic_library,
            ACTION_NAMES.cpp_link_nodeps_dynamic_library,
            ACTION_NAMES.lto_index_for_executable,
            ACTION_NAMES.lto_index_for_dynamic_library,
            ACTION_NAMES.lto_index_for_nodeps_dynamic_library,
        ],
        flag_groups = [
            flag_group(
                iterate_over = "runtime_library_search_directories",
                flag_groups = [
                    flag_group(
                        flags = [
                            "-Wl,-rpath,$ORIGIN/%{runtime_library_search_directories}",
                        ],
                    ),
                ],
                expand_if_available =
                    "runtime_library_search_directories",
            ),
        ],
        with_features = [
            with_feature_set(
                not_features = ["static_link_cpp_runtimes", "no_solib_rpaths"],
            ),
        ],
    )]

def _import_runtime_feature_impl(ctx):
    toolchain_import_info = ctx.attr.toolchain_import[CcToolchainImportInfo]
    static_link_flags = ctx.attr.static_link_flags

    linker_flags = depset([
        _file_to_library_flag(file, static_link_flags)
        for file in toolchain_import_info
            .linking_context.static_libraries.to_list()
    ] + [
        _file_to_library_flag(file, static_link_flags)
        for file in toolchain_import_info
            .linking_context.dynamic_libraries.to_list()
    ]).to_list()

    flag_sets = []

    if linker_flags:
        flag_sets.append(flag_set(
            actions = CC_LINK_EXECUTABLE_ACTION_NAMES,
            flag_groups = [
                flag_group(
                    flags = linker_flags,
                ),
            ],
        ))

    linker_flags_for_shared_obj = depset(_filter_for_shared_obj([
        _file_to_library_flag(file, static_link_flags)
        for file in toolchain_import_info
            .linking_context.static_libraries.to_list()
    ]) + [
        _file_to_library_flag(file, static_link_flags)
        for file in toolchain_import_info
            .linking_context.dynamic_libraries.to_list()
    ]).to_list()

    if linker_flags_for_shared_obj:
        flag_sets.append(flag_set(
            actions = [ACTION_NAMES.cpp_link_dynamic_library, ACTION_NAMES.cpp_link_nodeps_dynamic_library],
            flag_groups = [
                flag_group(
                    flags = linker_flags_for_shared_obj,
                ),
            ],
        ))

    library_feature = _feature(
        name = ctx.label.name,
        enabled = ctx.attr.enabled,
        flag_sets = [],
        #flag_sets
        #    + _get_runtime_library_search_directories_flags()
        #    + _get_libraries_to_link_flags(),
        implies = ["runtime_library_search_directories"] + ctx.attr.implies,
        provides = ctx.attr.provides,
    )
    return [library_feature, ctx.attr.toolchain_import[DefaultInfo]]

cc_toolchain_import_runtime_feature = rule(
    _import_runtime_feature_impl,
    attrs = {
        "enabled": attr.bool(default = False),
        "provides": attr.string_list(),
        "requires": attr.string_list(),
        "implies": attr.string_list(),
        "toolchain_import": attr.label(providers = [CcToolchainImportInfo]),
        "static_link_flags": attr.string_list(),
    },
    provides = [FeatureInfo, DefaultInfo],
)
