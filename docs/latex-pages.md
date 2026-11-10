# Build a LaTeX document to GitHub Pages

`latex-to-pages.yaml` publishes a LaTeX document as a PDF on GitHub Pages. Use it for a paper or course notes kept in a
repository: pull requests build the PDF so a broken document fails review, and `main` deploys it.

```yaml
name: Build LaTeX document
on:
  workflow_dispatch:
  push:
    branches: ["main"]
  pull_request:
  schedule:
    - cron: "0 8 * * *"
permissions: {}
jobs:
  pdf:
    uses: tox-dev/github-workflows/.github/workflows/latex-to-pages.yaml@SHA
    permissions:
      contents: write
      pages: read
    with:
      root-file: main.tex
```

Input `root-file` (default `main.tex`): the root TeX file latexmk compiles. The PDF keeps its base name and is served at
`https://<owner>.github.io/<repo>/<name>.pdf`.

- `build` (`📕 Compile LaTeX document`, `contents: read`, 20-minute timeout) compiles with latexmk, pins
  `SOURCE_DATE_EPOCH` to the checked-out commit time so the PDF is reproducible, and uploads it as the `latex-pdf`
  artifact, kept 30 days.
- `deploy` (`🚀 Deploy to GitHub Pages`, `contents: write` and `pages: read`, 30-minute timeout) runs only on `main`, in
  the `release` environment. It pushes the PDF to `gh-pages` as a single commit, replacing that branch's history, then
  polls for up to 20 minutes until Pages serves a PDF with the built SHA256.

Setup: enable GitHub Pages for the `gh-pages` branch, and create a `release` environment that allows `main`.

Runs are grouped per ref; a newer run cancels an older one except on `main`. The `deploy` job runs only when the ref is
`main`, so the `pull_request` trigger in the example builds the PDF without deploying it.
