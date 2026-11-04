Add `build-maturin-wheels.yaml`, a reusable workflow that builds a maturin extension's wheels and sdist from a JSON
build matrix. It uploads them under the artifact names the caller's publisher expects, builds from the hash-checked
build group of the caller's lock, and runs with no write token. Optional `pre-build-command` and `post-build-command`
inputs run the caller's own steps once before the wheels and on each wheel job's `dist` directory.
