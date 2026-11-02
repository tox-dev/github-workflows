`validate-news` passes at once for a label added or removed within a minute of a pull request opening, as
`gh pr create --label` does, since the run for the opening already checks the current labels.
