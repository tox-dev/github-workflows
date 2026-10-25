Add a temporary `nab-git-commit` input to `refresh-release-lock` and the reusable workflows that call it. A full commit
SHA installs Nab from `notatallshaw/nab` at that commit, with no cooldown, until a Nab release carries the fix.
