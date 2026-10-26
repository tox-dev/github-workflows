Stop re-checking files the release jobs produce themselves in the JetBrains Actions. `sign-jetbrains-plugin` no longer
runs `unzip -t` on the unsigned or signed ZIP, checks for Java 17 or an existing signed ZIP, runs the signer's `verify`,
or checks the signed ZIP's type and members. `publish-jetbrains-marketplace` no longer runs `unzip -t`, re-hashes the
upload copy, or checks the file types of a downloaded receipt and earlier artifacts.
