# SEC-004: staff password policy tranche

New staff accounts (initial administrator and users created by an administrator)
require a password of 15–1024 characters. Spaces and Unicode are permitted; no
letter/digit/symbol composition rule applies. The server rejects exact matches
to a bundled offline list of 10,000 common passwords after case folding. The
list comes from [SecLists, `10k-most-common.txt`](https://github.com/danielmiessler/SecLists/blob/master/Passwords/Common-Credentials/10k-most-common.txt)
under its MIT license, copied alongside the list in the auth package. This is
not a comprehensive compromised-password service; periodically updating the
list is necessary.

New password hashes use bcrypt over SHA-256 of the full UTF-8 password to avoid
bcrypt's 72-byte truncation. The prefixed hash format distinguishes them from
legacy bcrypt hashes. Existing accounts keep their current passwords; legacy
hash verification rejects input over 72 bytes to avoid a truncated-prefix
match. The patient portal retains its own enrollment policy for now.

This tranche does **not** close SEC-004. Staff MFA enrollment, login challenge,
recovery, and regression tests are required before treating single-factor
authentication as resolved. Any rollout must allow existing staff to enroll
without issuing a full-access session from a password-only login.

Policy references: [NIST SP 800-63B](https://pages.nist.gov/800-63-4/sp800-63b.html)
and [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html).
