

SysrootVarsInfo = provider(
    doc = "The absolute path to sysroot",
    fields = {"sysroot_root_path": "The absolute path to sysroot"},
)

def _sysroot_vars_impl(ctx):
    return [SysrootVarsInfo(sysroot_root_path = ctx.attr.sysroot_root_path)]

sysroot_vars = rule(
    implementation = _sysroot_vars_impl,
    attrs = {
        "sysroot_root_path": attr.string(mandatory = True),
    },
)

