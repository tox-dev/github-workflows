Add `check-tagged-source`, which runs the tag, lock, frozen hook, and cooled `prek` checks of a tagged checkout. The
Python release workflow uses it, and custom tag release jobs can call it before publishing.
