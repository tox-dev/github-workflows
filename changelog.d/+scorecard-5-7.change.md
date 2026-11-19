The shared Scorecard workflow runs OpenSSF Scorecard v5.7.0, which recognizes GitHub immutable releases in the
Signed-Releases and Pinned-Dependencies checks. The job disables cache access and fails if the Scorecard API rejects
publication. It still uploads the scan to GitHub code scanning when the results file is available.
