# channel-pages.md — Changelog

## Error Handling

### 2026-03-03 — PR #1477230 by Mario Siric
**Changed:** Added `errorDisplayDetails` pattern to `FluidChannelPageError` component and `ErrorPageSlot` interfaces, enabling specific error messages (e.g., `ChannelPageOutOfStorageError`) instead of generic fallbacks.
**Why:** The existing 507 (Insufficient Storage) handler in `handleFileCreationError` was never firing because the HTTP status code was lost during error flattening in the CDL worker resolver. Users saw a generic error page and 91% never recovered. This PR fixed status code propagation and added targeted error display via `errorDisplayDetails`.

---

## Server-Side Resolver

### 2026-03-03 — PR #1482424 by Mario Siric
**Changed:** All CDL workflow calls (`createFluidFile`, `createTab`, `updateTab`) in the Channel Pages provisioning resolver now execute at `IJobQueuePriority.REALTIME` instead of the default `NORMAL` priority.
**Why:** Channel Page tab creation was competing with background CDL work at `NORMAL` priority, causing job queue starvation that manifested as `SimpleWorkflow timed out after 180000 ms` errors. Since this is a user-initiated action, REALTIME priority prevents starvation while leaving all other tab operations at NORMAL.

### 2026-03-03 — PR #1477230 by Mario Siric
**Changed:** The resolver's catch block now preserves `serverResponse.status` from parent exceptions when flattening errors via `Object.assign`.
**Why:** For EPM `RequireStatusFailed` errors, `innerException` is an array (`["INSUFFICIENT_STORAGE"]`) rather than an object, so `Object.assign` copied array indices instead of the HTTP status code. This caused the client-side 507 handler to never fire, inflating failure metrics.

---

## Detached Container Pattern & File Creation

### 2026-03-03 — PR #1486370 by Mario Siric
**Changed:** Extended the `DuplicateDocumentServiceError` check in `getFluidOnPageLoad` to also match "Attempted to overwrite componentUrl" errors from concurrent provision race conditions, reusing the existing remount recovery path.
**Why:** When two concurrent `provisionFluidForChannelPageTab` invocations race on the same tab, the second one finds a different `componentUrl` already set and throws an unhandled error (~90/week, ~6% of all create failures, >50% of affected users never recovered). The fix routes this through the existing `DuplicateDocumentServiceError` remount recovery.

### 2026-03-03 — PR #1480212 by Mario Siric
**Changed:** Added `executeMutationWithRetry` to `ChannelPageDocumentServiceFactoryProxy` — retries the `provisionFluidForChannelPageTab` mutation once with 2.5s backoff on timeout. Gated by new `enableChannelPagesFileCreationRetry` flag.
**Why:** The Vroom `createFluidSnapshot` API times out at the EPM default of 30s with a 2-10% timeout rate. Telemetry showed bimodal latency (successful calls <12s, timeouts hit exactly 30s), so a longer timeout wouldn't help — a retry to a fresh server instance resolves it. Without retry, ~60 users/week lost in-memory content.

---

## Feature Flags & Settings

### 2026-03-03 — PR #1480212 by Mario Siric
**Changed:** Added new setting `enableChannelPagesFileCreationRetry` (Boolean, not CDL Worker) to control retry behavior for `createFluidSnapshot` timeouts during file creation.
**Why:** The retry mechanism for file creation timeouts needs controlled rollout. The flag was added to the GraphQL schema, ECS config, and ownership files.

---
