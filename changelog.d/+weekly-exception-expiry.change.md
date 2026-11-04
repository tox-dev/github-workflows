`upgrade-release-tools.yaml` checks cutoff exceptions before it refreshes the lock. A scheduled run now fails on an
expired or undated exception and names the package, even when no release input changed.
