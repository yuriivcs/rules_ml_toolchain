

SysrootVarsInfo = provider(
    doc = "The absolute path to sysroot",
    fields = {"sysroot_repo_name": "The absolute path to sysroot"},
)

def _sysroot_vars_impl(ctx):
    return [SysrootVarsInfo(sysroot_repo_name = ctx.attr.sysroot_repo_name)]

sysroot_vars = rule(
    implementation = _sysroot_vars_impl,
    attrs = {
        "sysroot_repo_name": attr.string(mandatory = True),
    },
)
