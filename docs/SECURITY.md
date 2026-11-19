# Security boundaries

Use synthetic data only. `SYN-` references reduce accidental misuse but do not detect or redact real information entered into free text.

The application uses three role-level random bearer keys. They identify demo roles, not individual employees. Audit actors such as `demo-agent` must not be represented as individual accountability. Shared keys must be replaced with individual identity/SSO before operational use.

The API enforces access independently of the interface. Auditors cannot create cases. Queue responses omit customer references and message bodies. Detail and audit access is permitted to all authenticated demonstration roles.

Credentials live in ignored `.env` files. Bootstrap never overwrites existing credentials. API validation errors omit submitted values. Database exception responses do not expose SQL or input data. No application logger records request bodies, tokens, or email content.

Audit creation is atomic with intake and every workflow mutation, but records are not immutable against database administrators. Workflow audit details intentionally retain synthetic answer history; all authenticated demo roles may read this history. Retention, tamper-evident storage, read-access auditing, backups, encryption, key rotation, request limits, and SSO remain deployment work.

Keep services on localhost in development. Public deployment requires HTTPS, individual authentication, rate limiting, secret management, dependency review, backup/restore checks, and explicit access configuration. No production-compliance claim is made.

## Milestone 2 controls

All workflow writes require the case version last seen by the caller. A database version predicate rejects a competing write even when both requests passed the initial version check. Query and commitment changes also increment the parent case version. A conflict returns 409 and requires refresh.

Agent keys represent one shared `demo-agent` identity. Agents can claim cases for that identity and change cases it owns. Managers can assign either demo owner and intervene in any case. Auditors cannot write. A case in `pending_review` can only be resolved or returned to work by a manager. This is a demonstration of roles, not employee-level authorization.

Recording an evidence reference does not verify its truth or approve a policy outcome. The human reviewer must assess accuracy. No response has been delivered merely because a case is resolved or closed. Reopening preserves the old answers in audit details and resets the current query checklist.
