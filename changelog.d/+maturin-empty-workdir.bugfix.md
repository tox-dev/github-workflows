The `build` and `sdist` jobs of `build-maturin-wheels` no longer print setup-uv's "Empty workdir detected" warning: they
set up uv while the source still downloads, as `github-release` already allowed for.
