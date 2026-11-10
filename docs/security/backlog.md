# Security backlog
Medium/low findings from security-breaker runs. Cleared in the User simulation phase.

- [ ] (P0–P7 review, F11, medium) dnspython 2.8.0 (transitive via ciscoconfparse2) has CVE-2026-114605, fixed in 2.9.0; netarch does no DNS wire parsing. Fix: pin `dnspython>=2.9.0` in pyproject and re-run the gate.
- [ ] (P0–P7 review, F14, low) The export ZIP leaves out secrets.txt, but every config inside it carries the enable/admin secrets and PSKs, and one enable/admin pair is shared by all devices. Options: document the ZIP as sensitive (README) or generate per-device passwords.
