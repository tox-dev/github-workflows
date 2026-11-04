`refresh-release-lock` in `check` mode, which `validate-news` runs, fails for a `[tool.nab]` cutoff exception that has
no `# expires YYYY-MM-DD` comment directly above it, has a malformed date, or has passed its date. The error names the
package. Add the comment above each existing exception.
