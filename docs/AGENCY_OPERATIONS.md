# Agency Operations

Phase 7 establishes a bounded operating loop:

```text
evidence-backed research -> qualification -> persistent CRM
-> local outreach draft -> scoped approval -> provider send + verification
-> reply evidence -> lead transition -> follow-up / meeting context
```

Lead research requires a healthy provider and source evidence. The deterministic mock provider is allowed only in tests and labels every claim `test-fixture`. Production defaults to disconnected and returns unavailable instead of generating companies.

Qualification records score, reasons, and evidence. Outreach drafts use a CRM lead with a verified email and are never sent automatically. DNC leads are rejected. Reply transitions require a provider message ID. Meeting preparation combines connected calendar data with persistent CRM context; missing sources are labeled.

Client Manager, Lead Research, Outreach, and Meeting agents are declarative bounded roles. Their readiness does not make disconnected integrations available and does not grant external authority.
