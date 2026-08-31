# Spire Releases — Agent Contract

**Universal coding policy:**
`/Users/jeremyserna/truth_forge/docs/ecosystem/BUILD_PROCESS_PORTABLE.html`.
Read it before creating or materially changing software or release automation.
`CODE_POLICY_BINDING.json` is this repository's machine-readable pointer to that
policy, not a policy copy.

This repository is the public release channel for Spire. Spire source,
architecture, tests, packaging logic, signing logic, and release automation live
in `/Users/jeremyserna/apps_dev/spire`. This repository owns only the published
release-site records and release artifacts intentionally placed here.

## Rules

- Never treat an uploaded file, appcast entry, signature, or notarization claim
  as valid without the matching Spire release receipt and artifact digest.
- Do not copy Spire source or internal engineering documents into this channel.
- Publishing, replacing, or deleting a release is an external action and requires
  the operator's explicit release authority.
- Preserve unrelated work and commit only files in the current task by explicit
  path.

## Verification

Run `pre-commit run --all-files`. For any release change, also verify the appcast,
download URL, artifact digest, signature, notarization receipt, and clean-machine
installation against the exact candidate named by Spire's release record.
