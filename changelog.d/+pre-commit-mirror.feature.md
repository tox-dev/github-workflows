Add `publish-pre-commit-mirror.yaml`, a reusable workflow for pre-commit mirrors that pins the mirror maker and prek,
fails on a clean-tree mismatch instead of masking it, refuses to move a published tag, and pushes the branch and tag in
one atomic push.
