# Copyright 2025 Google LLC
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

load("@bazel_tools//tools/build_defs/repo:local.bzl", "new_local_repository")

# Use cases
# Darwin -> Darwin
#   Default value: $(xcrun --show-sdk-path)
#       or
#   Developer can override this value with help of MACOS_SYSROOT_PATH environment variable

# Linux -> Darwin
#   Require valid path to available sysroot or print error otherwise
def _macos_local_sysroot_impl(ctx):
    sdk_path = ctx.os.environ.get("MACOS_SYSROOT_PATH", "")

    if not sdk_path:
        res = ctx.execute(["xcrun", "--show-sdk-path"])
        if res.return_code != 0:
            fail("Failed to find macOS SDK via xcrun: " + res.stderr)
        sdk_path = res.stdout.strip()

    print("macos_local_sysroot: sdk_path = " + sdk_path)
    links = ["System", "usr"]
    for link in links:
        ctx.symlink(sdk_path + "/" + link, link)

    ctx.symlink(ctx.path(ctx.attr.build_file), "BUILD.bazel")

macos_local_sysroot = repository_rule(
    implementation = _macos_local_sysroot_impl,
    local = True,
    environ = ["MACOS_SYSROOT_PATH"],
    attrs = {
        "build_file": attr.label(
            doc = "A file to use as a BUILD file for this repo.",
            mandatory = True,
        ),
    },
)