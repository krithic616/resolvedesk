# Security boundaries

Use synthetic data only. `SYN-` references reduce accidental misuse but do not detect or redact real information entered into free text.

Milestone 1 uses three role-level random bearer keys. They identify demo roles, not individual employees. Audit actors such as `demo-agent` must not be represented as individual accountability. Shared keys must be replaced with individual identity/SSO before operational use.

The API enforces access independently of the interface. Auditors cannot create cases. Queue responses omit customer references and message bodies. Detail and audit access is permitted to all authenticated demonstration roles.

Credentials live in ignored `.env` files. Bootstrap never overwrites existing credentials. API validation errors omit submitted values. Database exception responses do not expose SQL or input data. No application logger records request bodies, tokens, or email content.

Audit creation is atomic with intake, but records are not immutable against database administrators. Retention, tamper-evident storage, read-access auditing, backups, encryption, key rotation, request limits, and SSO remain deployment work.

Keep services on localhost in development. Public deployment requires HTTPS, individual authentication, rate limiting, secret management, dependency review, backup/restore checks, and explicit access configuration. No production-compliance claim is made.
