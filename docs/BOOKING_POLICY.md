# VYOM Booking Policy

## Scope

Phase 8 ships the `BookingTask` architecture
(`services/brain/app/booking/`), not every booking provider. Initial
categories: `restaurant`, `appointment`, `meeting`, `hotel`,
`travel-research`, `service-booking`. `BookingSearchService` is provider-
pluggable per category and defaults to `DisconnectedBookingProvider` —
production reports an honest unavailable result until a real provider is
configured, matching the Phase 7 integration honesty pattern.
`MockBookingProvider` exists for tests/demos only and labels every option
`provider="test-fixture"`.

## Flow

```text
Understand requirement (BookingPlanner)
  -> Retrieve preferences
  -> Research options (BookingSearchService)
  -> Compare (BookingComparator)
  -> Show recommendation
  -> User approval where required
  -> Reserve (BookingReservationService)
  -> Verify confirmation (BookingVerifier)
  -> Save confirmation (BookingStore)
  -> Calendar update if allowed (future work)
```

## Constraints

`BookingConstraints` carries `date`, `time`, `location`, `budget`,
`party_size`, `preferences`, `cancellation_policy`, `distance_km`, and
`minimum_rating`. `BookingComparator` never silently relaxes an important
constraint: an option that does not match is still returned, but with
`matches_constraints=False` and an explicit `relaxed_constraints` list so
the alternative is visibly labeled, not hidden.

## Permission boundary

| Action | Level |
| --- | --- |
| Research / compare options | L0 / L1 |
| Reserve a no-cost slot | L2 (`PermissionEngine` L2 markers: "book a", "reserve a") |
| Payment | L3 (`PermissionEngine` L3 markers: "pay", "payment") |

Phase 8 does not autonomously complete a monetary purchase. Before payment,
the workflow must show merchant, item/service, total price, currency,
fees, and cancellation/refund terms, and require explicit approval — no
payment execution path exists yet (see "Important limits" below).

## Verification

A click on "Book" is never completion. `BookingConfirmation.apply` only
moves a request to `RESERVED` when the provider response includes a
`confirmation_id`; `BookingVerifier` additionally requires a recorded
date/time, provider, and final price (when applicable) before marking a
request `CONFIRMED`.

## Duplicate prevention

`BookingRequest.compute_idempotency_key` hashes category + constraints.
`BookingReservationService.reserve` looks up any existing request with the
same key that is already `RESERVED`/`CONFIRMED` and raises
`DuplicateBookingError` instead of creating a second reservation — this
holds across retries and process restarts because the key is persisted in
`BookingStore` (SQLite).

## Booking memory

Learned preferences (aisle seat, hotel budget range, dietary preference)
are stored through the existing Phase 6 memory system, following its
provenance/confidence rules — Phase 8 does not add a separate preference
store.

## Important limits (not yet implemented)

Autonomous purchasing, real payment execution, unrestricted provider
integration, and calendar write-back are explicitly out of scope for this
phase (see `VYOM_IMPLEMENTATION_STATUS.md`).
