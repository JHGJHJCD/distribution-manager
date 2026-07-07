"""Single source of truth for the application version.

Bump this on every release and publish a matching GitHub release tagged
``v<APP_VERSION>`` (e.g. v1.1) with the EXE attached as ``Manhal-Haluka.exe``.
The in-app updater compares this value against the latest GitHub release.
"""
APP_VERSION = "2.36"
