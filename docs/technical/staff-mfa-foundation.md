# SEC-004: staff MFA storage foundation

This migration adds three staff-only tables and changes no authentication endpoint.
Password-only login, setup, and refresh still issue their current sessions until
a later coordinated enforcement change. This PR must remain draft and must not be
described as completing SEC-004.

- `staff_mfa_factors` has one row per staff user. `encrypted_secret` must hold
  only an authenticated-encryption envelope, never a raw TOTP seed; `key_id`
  identifies a separately managed encryption key for rotation. A factor with
  `enrolled_at = NULL` is pending; its `pending_expires_at` bounds setup.
  `last_accepted_step` supports one-use TOTP steps under a row lock.
- `staff_mfa_challenges` stores a digest of an opaque password-verified
  challenge, its purpose, expiry, attempts, and consumption time. A challenge
  must never be accepted as an API access or refresh credential. Later handlers
  must lock rows before counting attempts and consuming challenges.
- `staff_mfa_recovery_codes` stores only digests of independently generated,
  high-entropy, one-use codes. Later handlers must atomically mark use,
  replace a used code, and notify the account owner.

The migration does not backfill factors or silently enable MFA for existing
accounts. Before enforcement, implement and test enrollment, an operator
bootstrap for the first administrator, existing-account migration, factor
challenge and recovery, key management, revocation, and browser UI as tracked
in [SEC-004 issue #62](https://github.com/mahmoodianasl-svg/dentalpin/issues/62).
The first enforcement release must not issue full-access sessions from a
password-only login; establish a controlled path for existing staff to enroll
without a bypass to patient data.

Do not persist pending TOTP material unless a production encryption key is
configured. Backups of these tables require the separately stored key for
restoration. Recovery-code digests must not use the token-signing secret.

## Qualification

This stacked PR temporarily targets `main` to trigger the repository's
pull-request CI, which is configured for `main` and `develop` rather than
feature-to-feature PRs. Once exact-head gates pass, restore the PR base to
the password-policy branch to keep its diff limited to this tranche.
