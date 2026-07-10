# Automated release state

The maintenance automation writes `release.json` only after it has implemented
and validated the changelog from an existing final GitHub release.

Updating that manifest triggers the release-assets workflow. The workflow
builds from the updated `main` commit and attaches the resulting ZIP, tarball,
wheel, and checksum file to the existing release without moving its tag.

