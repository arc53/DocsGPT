# Run in every sandbox kernel at start, after ipykernel has set up its environment.
#
# ipykernel's shell sets FORCE_COLOR=1 and CLICOLOR_FORCE=1 for the programs a
# kernel starts, so Node, npm, pip and other tools colour their output even into
# a pipe. The model reads that output as text, where colour codes are only noise
# (the app strips them too, as a backstop), so drop both and set NO_COLOR.
#
# kernel-launch.sh loads this with --IPKernelApp.exec_files. It runs in the
# user's namespace, so it uses comments rather than a docstring and deletes the
# names it binds.
import os as _docsgpt_os

for _docsgpt_name in ("FORCE_COLOR", "CLICOLOR_FORCE"):
    _docsgpt_os.environ.pop(_docsgpt_name, None)
_docsgpt_os.environ["NO_COLOR"] = "1"
del _docsgpt_os, _docsgpt_name
