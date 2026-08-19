# Spire — Releases

This repository is the **distribution channel** for [Spire](https://updates.noeticaperture.com),
an Apple-native macOS application for running Linux containers through Apple's `container`
runtime, with on-device MLX inference serving built in.

- **Download:** [updates.noeticaperture.com](https://updates.noeticaperture.com) or the
  [releases page](https://github.com/Truth-Forge/spire-releases/releases)
- **Bug reports & questions:** [Issues](https://github.com/Truth-Forge/spire-releases/issues)
- **Update feed:** `https://updates.noeticaperture.com/spire/appcast.xml` (Sparkle 2)

Every release artifact is signed with a Developer ID certificate, notarized by Apple, and
additionally signed with Spire's EdDSA update key. The app verifies both before installing
an update.

## Release provenance

The file spire/releases.json is the immutable release ledger. Every published
build is bound to the exact private-source commit used to build it and to the
SHA-256 digest GitHub calculated for its primary ZIP asset. The public CI check
also verifies every current Sparkle enclosure against the live GitHub Release
asset name and byte length.

Run the complete publication check with
python3 scripts/validate_release_feed.py --github-live.

Spire is © 2026 Truth Forge LLC, licensed under the Apache License 2.0.
