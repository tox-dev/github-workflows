# Security policy

github-workflows is a set of composite actions and reusable workflows that check pull request news and locks, prepare
and tag releases, and publish them to PyPI, GitHub and the JetBrains Marketplace. This policy says how to report a
security problem and how we decide whether a report is one.

## Reporting a vulnerability

**Do not open a public issue for a security problem.** Use
[GitHub's private vulnerability reporting](https://github.com/tox-dev/github-workflows/security/advisories/new). If
neither works for you, email [gaborjbernat@gmail.com](mailto:gaborjbernat@gmail.com).

Include what the attacker controls and what they gain, the steps or a proof of concept, and the versions and platform
you tested. Write the report yourself; unreviewed tool or model output takes longer to triage.

## What to expect

Volunteers maintain github-workflows, with no on-call rotation. We aim to acknowledge a report within **5 working days**
and assess it within **15 working days**. Fixes are developed in a private fork attached to the draft advisory, ship in
a new release, and the advisory, with a CVE requested through GitHub, goes out with that release. The default embargo is
**90 days** from the report; we agree any change with the reporter. We credit reporters in the advisory under the name
they choose, or not at all. There is no bug bounty.

## Supported versions

Only the latest release receives fixes. Callers pin a full commit SHA; Dependabot moves the pin.

## Vulnerability or bug

A report is a vulnerability when an attacker who controls only an input that the [threat model](THREAT_MODEL.md) lists
as untrusted breaks a guarantee github-workflows makes. A report that first needs control of something the threat model
trusts, such as a calling workflow's triggers, permissions or secrets, or a maintainer-approved release dispatch, is a
bug: we fix it in the open and publish no advisory. Classify by who supplies the dangerous input, not by how bad the
outcome sounds.

**In scope**

- Pull request content (fragments, locks, `pyproject.toml`) reaching a shell as code, or gaining a write token or a
  secret.
- A release patch that `validate-release-patch` accepts although it touches paths other than the changelog and fragment
  deletions, or changes file modes.
- A step that publishes files whose digests or attestations do not match what the build produced.
- A locked tool installed without its hash check, or any tool installed ahead of its upload cutoff.
- An App token or credential reaching a step that runs project or third-party code.

**Out of scope**

- How a calling repository configures its triggers, environments, rulesets and secrets.
- Code the caller's own build runs: the build job is read-only by design, and only its outputs are verified.
- Vulnerabilities in GitHub Actions, PyPI or the JetBrains Marketplace themselves.

If you cannot tell which side a finding falls on, report it privately and we will decide.
