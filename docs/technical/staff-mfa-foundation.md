# SEC-004: staff MFA storage foundation

Status: partial implementation — storage and cryptographic primitives only; enforcement pending.

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

## Cryptographic primitives

The storage foundation includes a settings-independent MFA service layer. It
uses standard 30-second, six-digit HMAC-SHA-1 TOTP for authenticator-app
compatibility, permits at most one adjacent time step, and returns the accepted
step so callers can atomically prevent replay with `last_accepted_step`.

TOTP seeds use AES-256-GCM with the staff user ID and key ID as associated data.
The encryption key is explicit and must decode to exactly 256 bits; missing or
malformed material fails closed. Pending-auth challenges contain 256 random
bits and persist only a SHA-256 digest. Recovery codes contain 128 random bits
and persist only an HMAC-SHA-256 digest under an independent pepper of at least
256 bits. The module does not read configuration or issue sessions; endpoint
wiring must source encryption keys and recovery peppers from secret management,
apply database row locks, expiry and attempt limits, and avoid logging inputs.

The deployment surface now exposes `MFA_ENCRYPTION_KEY_ID`,
`MFA_ENCRYPTION_KEY`, and `MFA_RECOVERY_PEPPER`. The two secret values are
Base64- or Base64URL-encoded independent random values of at least 256 bits and
must come from deployment secret management, not the repository. The key
loader validates all three values before use. Empty defaults keep the
not-yet-enforced foundation bootable but fail closed when an MFA operation
requests the keys.

The service can construct a five-minute pending-auth row for `login`,
`enrollment`, or `recovery`. It stores only the opaque challenge digest,
starts with zero attempts, rejects a fifth attempt, and rejects expired or
consumed rows. Endpoint code must obtain the row with `SELECT ... FOR UPDATE`
before incrementing attempts or consuming it; these helpers intentionally do
not pretend an in-memory check is an atomic database transition.
