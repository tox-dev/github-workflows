The `codeql.yaml` reusable workflow runs CodeQL for a list of languages, with inputs for ignored paths, query suite,
configuration file, and build mode. A caller keeps its own triggers and grants `security-events: write`.
