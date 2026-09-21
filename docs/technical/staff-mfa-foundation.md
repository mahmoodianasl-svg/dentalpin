# SEC-004: staff MFA storage foundation

Status: partial implementation — storage, cryptographic primitives, staff
enrollment endpoints, and password-plus-MFA login; universal rollout pending.

The `0008` migration adds three staff-only tables. The `0009` migration adds a
verification timestamp to browser refresh sessions. Once a staff account has
an enrolled factor, password login returns a five-minute challenge without
issuing access or refresh credentials. `/auth/mfa/complete` accepts a TOTP or
unused recovery code, consumes the challenge under a row lock, and issues a
verified browser session. Five failed attempts exhaust a challenge. Existing
access tokens without MFA proof are rejected, and old refresh sessions are
revoked on refresh. This PR must remain draft until SEC-004 rollout is complete.

The enrolled factor row lock also enforces a ten-attempt budget across login
challenges issued to the same account in the last ten minutes. A new password
challenge cannot reset this budget; completion returns 429 until the older
challenges leave the window. The per-challenge five-attempt and five-minute
expiry checks still apply.

Authenticated staff can start enrollment at `/auth/mfa/enroll/start` with a
fresh password recheck. It returns a five-minute challenge and authenticator
setup URI, stores the seed only as an encrypted envelope, and expires pending
setup after ten minutes. Restarting setup invalidates prior challenges.
`/auth/mfa/enroll/confirm` validates the pending TOTP step under row locks,
marks the factor enrolled, revokes older browser sessions and access tokens,
and creates a verified browser session. The ten recovery codes are shown only
in this response; only keyed digests are persisted. The profile screen shows
them once and asks the user to store them safely before leaving the screen.
The browser login screen accepts an authenticator code or an unused recovery
code after password verification. The pending challenge stays in page memory.
`/auth/mfa/status` returns enrollment state and the number of unused recovery
codes for the authenticated staff profile screen.
An enrolled staff member can rotate recovery codes at
`/auth/mfa/recovery/rotate` using the current password and a fresh, non-replayed
authenticator code. The factor row lock serializes this step-up with other MFA
operations. Rotation deletes every old recovery-code digest and inserts ten new
ones in one transaction. The profile shows the replacement codes only once;
old codes stop working immediately. This self-service path requires possession
of the authenticator and does not recover a lost device.

- `staff_mfa_factors` has one row per staff user. `encrypted_secret` must hold
  only an authenticated-encryption envelope, never a raw TOTP seed; `key_id`
  identifies a separately managed encryption key for rotation. A factor with
  `enrolled_at = NULL` is pending; its `pending_expires_at` bounds setup.
  `last_accepted_step` supports one-use TOTP steps under a row lock.
- `staff_mfa_challenges` stores a digest of an opaque password-verified
  challenge, its purpose, expiry, attempts, and consumption time. A challenge
  must never be accepted as an API access or refresh credential. The login
  completion handler locks the challenge before counting attempts or consuming it.
- `staff_mfa_recovery_codes` stores only digests of independently generated,
  high-entropy, one-use codes. Login completion atomically marks use; issuing a
  replacement on recovery-code login and notifying the account owner remain
  rollout work.

The migrations do not backfill factors or silently enable MFA for existing
accounts. Password-only login still issues full sessions for staff without an
enrolled factor. Before production enforcement, finish the operator bootstrap
for the first administrator, existing-account migration, automatic replacement
and owner notification after recovery-code login, lost-device recovery, key
management, and audit as tracked
in [SEC-004 issue #62](https://github.com/mahmoodianasl-svg/dentalpin/issues/62).
The first universal enforcement release must establish a controlled path for
existing staff to enroll without a bypass to patient data.

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

The service constructs a five-minute pending-auth row for `login`,
`enrollment`, or `recovery`. It stores only the opaque challenge digest,
starts with zero attempts, rejects a fifth attempt, and rejects expired or
consumed rows. The login and enrollment endpoints obtain the row with
`SELECT ... FOR UPDATE` before incrementing attempts or consuming it. A
factor-recovery flow must apply the same transaction discipline when added.
