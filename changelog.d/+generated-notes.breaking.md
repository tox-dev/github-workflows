Remove GitHub's generated notes from the release path: the `generated-notes` input of `render-release-notes` is gone,
and the github-workflows release no longer has a Contents-write job that fetches contributor metadata. The read-only
notes job now runs in parallel with the tag check and renders the notes from the full history alone.
