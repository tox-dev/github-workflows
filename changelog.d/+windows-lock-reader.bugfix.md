`install-locked-tools` installs the lock reader on Windows again: it ran the installer from the lock reader's own
interpreter, and Windows refused to replace that running `python.exe` when the installer recreated the environment.
