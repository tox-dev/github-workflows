Add `publish-pre-commit-mirror.yaml`, a reusable workflow for pre-commit mirrors that pins the mirror maker and prek,
checks formatting with a second run, never moves a published tag, treats an already-published identical version as a
no-op, and pushes the branch and tag in one atomic push.
