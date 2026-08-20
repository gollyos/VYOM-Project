# VYOM Client Delivery

## Purpose

`ClientDeliveryService` (`services/brain/app/delivery/client_delivery.py`)
packages verified artifacts for a client and gates external send behind
quality checks and approval — VYOM may prepare a package automatically, but
the actual external send/upload requires approval unless explicitly
pre-authorized (default L2).

```text
Project deliverables (verified ArtifactRecords)
  -> Select approved/latest versions (PackageBuilder)
  -> Quality gate (QualityGate)
  -> Manifest (DeliveryManifest)
  -> Prepare package (ClientDeliveryService.prepare)
  -> Approval
  -> Send (ClientDeliveryService.send) -> provider evidence
  -> Verify (DeliveryVerifier)
```

## DeliveryPackage

`id, client, project, deliverables, manifest, version, quality_status,
approval_status, delivery_method, evidence, dedupe_key`.
`approval_status` moves `draft -> quality_checked -> awaiting_approval ->
approved -> sent` (or `failed`).

## Manifest

`DeliveryManifest` holds one `ManifestEntry` per deliverable: `deliverable,
file, version, description, created_at, verified`. Useful for multi-file
client work — every file in a delivery is individually traceable.

## Quality gate

Before delivery, `QualityGate.check` verifies: correct client, correct
project, all required deliverables present in the manifest, every artifact
is its latest validated/final version, no temporary/debug files
(`.tmp`, `.draft`, `.bak`, `~`), no secret-shaped content
(`api_key=`, `password=`, PEM private key headers, ...) in scannable
deliverable files, no obvious placeholder content (`lorem ipsum`, `TODO`,
`TBD`, `[insert`), and every manifest entry is verified. Any failed check is
reported by name in `QualityGateReport.issues`; delivery is blocked until
they pass.

## Approval boundary

`ClientDeliveryService.prepare` may run automatically once the quality gate
passes. `ClientDeliveryService.send` performs the actual external transport
and defaults to `DisconnectedDeliveryProvider` (honest unavailable) until a
real provider is configured; the `PermissionEngine` classifies delivery
phrasing ("send to client", "deliver to", "prepare everything ready to
send", "upload deliverable") as L2, so the Task Runtime pauses for approval
before this phase runs in production.

## Duplicate prevention

`DeliveryPackage.compute_dedupe_key` hashes client + project + version +
sorted deliverable titles. `prepare()` checks the persisted `DeliveryStore`
for an existing package with the same key already `sent`, and raises
`DuplicateDeliveryError` rather than silently overwriting a sent record or
resending after crash recovery. `send()` re-checks the same condition
immediately before transport.

## Delivery verification

After sending, `DeliveryVerifier.verify` requires a message ID or upload
URL, a provider confirmation, and a timestamp before marking the package
`SENT`/verified. A request-accepted response with no such evidence is never
treated as delivered.
