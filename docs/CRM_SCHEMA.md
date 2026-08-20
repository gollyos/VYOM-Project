# Internal CRM Schema

The Phase 7 CRM is local SQLite storage behind `CRMStore`. It supports durable record categories for clients, persons, leads, opportunities, projects, interactions, campaigns, and activity through the shared `CRMRecord` contract. The first exercised vertical slice uses typed `Lead` records.

Lead states are `new`, `researched`, `qualified`, `contacted`, `replied`, `meeting`, `proposal`, `won`, `lost`, and `do_not_contact`. Records include provenance-friendly evidence, score, qualification reason, contact fields, metadata, and timestamps.

Duplicate prevention uses `(record_type, normalized_key)`. Lead domains are normalized by removing scheme, `www`, punctuation, and case. An upsert reuses the existing record ID and original creation time instead of creating a duplicate.

External provider IDs and evidence belong in record metadata/interactions; credentials do not. DNC status is authoritative and blocks outreach transitions. CRM changes are L1 internal actions, while any resulting external send remains L2.
