# a package, so an installed "identity" distribution cannot shadow ours.
#
# Without this file the directory is a NAMESPACE portion: during the sys.path
# scan a namespace portion is only remembered, and a regular package found
# LATER on the path still wins -- even though the repo root was inserted first.
# `identity` is a real name on PyPI, so this is not hypothetical (Codex, PR #55).
