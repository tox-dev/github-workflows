Remove the `render-release-notes` `output` input. Every caller passed `${{ runner.temp }}/release-notes.md`, which is
now where the Action writes the body.
