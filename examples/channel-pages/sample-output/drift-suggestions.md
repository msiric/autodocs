---
date: 2026-03-03
suggestion_count: 7
verified: 7/7
---
# Suggested Updates — 2026-03-03

## channel-pages.md — Error Handling
**Triggered by:** PR #1477230 "Surface server response errors from parent exceptions"
**Confidence:** CONFIDENT

### FIND (anchor — insert after this line):
> | Domain | `useFluidFileDomainValidation` | URL hostname validation against allowed domains |

### INSERT AFTER:
> | Error display | `FluidChannelPageError` | Prioritizes `errorDisplayDetails` prop for error/detail message keys; falls back to default error mapping |

**Verified:** YES — anchor confirmed in doc (line 950)

### Reasoning:
PR #1477230 added `errorDisplayDetails` support to `FluidChannelPageError` and `ErrorPageSlot` interfaces so that specific errors like 507 out-of-storage display targeted messages instead of generic fallbacks.

---

## channel-pages.md — Server-Side Resolver
**Triggered by:** PR #1482424 "Elevate tab creation CDL workflow to REALTIME priority"
**Confidence:** CONFIDENT

### FIND (anchor — insert after this line):
> 6. **Return** `{ componentUrl, itemId, shareLink, shareId, spRequestGuid }`

### INSERT AFTER:
>
> **Priority:** All CDL workflow calls (`createFluidFile`, `createTab`, `updateTab`) execute at `IJobQueuePriority.REALTIME` to prevent starvation by background CDL work. All other tab operations (generic create, update, remove, migrate) remain at `NORMAL` priority.

**Verified:** YES — anchor confirmed in doc (line 474)

### Reasoning:
PR #1482424 threaded a `priority` parameter through the full call chain from the Channel Pages provisioning resolver to `simpleWorkflowStarter.execute()`, setting `REALTIME` for all three workflow calls to address `SimpleWorkflow timed out after 180000 ms` errors caused by job queue starvation.

---

## channel-pages.md — Server-Side Resolver
**Triggered by:** PR #1477230 "Surface server response errors from parent exceptions"
**Confidence:** CONFIDENT

### FIND (anchor — insert after this line):
> **Scenario:** `ScenarioName.FluidResolverProvisionChannelPageTab`

### INSERT AFTER:
>
> **Error handling:** The catch block preserves `serverResponse.status` from parent exceptions (e.g., EPM `RequireStatusFailed` with HTTP 507) so that client-side error handlers can identify specific failure types. Without this, error flattening via `Object.assign` loses the status code when `innerException` is an array rather than an object.

**Verified:** YES — anchor confirmed in doc (line 476)

### Reasoning:
PR #1477230 fixed a bug where `Object.assign(newError, error?.innerException)` copied array indices instead of the HTTP status code when `innerException` was `["INSUFFICIENT_STORAGE"]`, causing the 507 handler in `handleFileCreationError` to never fire.

---

## channel-pages.md — Detached Container Pattern & File Creation (Section 5.4)
**Triggered by:** PR #1486370 "Handle concurrent provision race condition for componentUrl overwrite"
**Confidence:** CONFIDENT

*Note: This was flagged under "Site Provisioning" but the code change is in `fluid-page-loader.ts` (Section 5.4 getFluidOnPageLoad), not in the site provisioning hook. Section 4 does not need updating from this PR.*

### FIND (in channel-pages.md, section "5.4 getFluidOnPageLoad"):
> - `DuplicateDocumentServiceError` → trigger `remountChannelPageContainer()` for retry

### REPLACE WITH:
> - `DuplicateDocumentServiceError` (duplicate document ID or concurrent `componentUrl` overwrite race) → trigger `remountChannelPageContainer()` for retry

**Verified:** YES — FIND text confirmed in doc (line 430)

### Reasoning:
PR #1486370 extended the `DuplicateDocumentServiceError` check in `getFluidOnPageLoad` to also match "Attempted to overwrite componentUrl" errors from concurrent provision race conditions, reusing the existing remount recovery path.

---

## channel-pages.md — Detached Container Pattern & File Creation (Section 5.3)
**Triggered by:** PR #1480212 "Add retry for createFluidSnapshot file creation timeout issue"
**Confidence:** CONFIDENT

### FIND (anchor — insert after this line):
> 7. Return document service for new resolved URL

### INSERT AFTER:
>
> **Timeout retry:** When `enableChannelPagesFileCreationRetry` is enabled, the proxy retries the `provisionFluidForChannelPageTab` mutation once with a 2.5s backoff if the call times out (EPM 30s default). The retry executes transparently within `createContainer` so the Fluid Framework never sees the first failure and the in-memory component stays alive.

**Verified:** YES — anchor confirmed in doc (line 416)

### Reasoning:
PR #1480212 added `executeMutationWithRetry` to `ChannelPageDocumentServiceFactoryProxy` to address a steady-state issue where ~60 users/week lost in-memory content when the Vroom `createFluidSnapshot` call timed out with no recovery path.

---

## channel-pages.md — Feature Flags & Settings
**Triggered by:** PR #1480212 "Add retry for createFluidSnapshot file creation timeout issue"
**Confidence:** CONFIDENT

### FIND (anchor — insert after this line):
> | `enableTrimChannelPageFilePath` | Boolean | Yes | Trim whitespace from file paths (CDL worker) |

### INSERT AFTER:
> | `enableChannelPagesFileCreationRetry` | Boolean | No | Retry `createFluidSnapshot` once on timeout during file creation |

**Verified:** YES — anchor confirmed in doc (line 851)

### Reasoning:
PR #1480212 added the `enableChannelPagesFileCreationRetry` feature flag to the GraphQL schema (`channelPages-settings.graphql`), ECS config, and ownership files to gate the new retry mechanism behind a controlled rollout.

---

## telemetry-guide.md — Known Channel Pages Failure Patterns
**Triggered by:** New telemetry anomalies (daily report 2026-03-03)
**Confidence:** REVIEW

### FIND (anchor — insert after this line):
> | `"Type: genericError Message: RequireStatusFailed"` (in `Scenario_Messaging_View.reason`) | HTTP 507 Insufficient Storage from Vroom `createFluidSnapshot` — user's OneDrive storage is full. Verify via `endpointns`: `apiName == "createFluidSnapshot"` + `result has "RequireStatusFailed"`. **Unlike tab creation errors, this appears in `endpointns`** (Vroom call, not CDL worker). | **Expected** (post-fix: scenario ends as `success`, error UI shown) |

### INSERT AFTER:
> | `"Error parsing snapshot response: Invalid code: 101"` (in `Scenario_Messaging_View.reason`) | Snapshot response from ODSP returned an unexpected status code during load. Possible transient ODSP issue or corrupted response. | **Unknown** — low volume, requires investigation |
> | `"Entry point of loaded package not a Fluid module. Trying to load ContainerType: @fluidx/loop-page-container"` | Fluid container entry point did not match expected module interface. May indicate version mismatch or corrupted package load. Appears in both create and load scenarios. | **Unknown** — low volume, requires investigation |
> | `"Type: genericError Message: 0x8e4"` | Unknown Fluid Framework error code, not documented in known error code ranges. | **Unknown** — low volume, requires investigation |

**Verified:** YES — anchor confirmed in doc (line 1000)

### Reasoning:
Three new error patterns appeared in telemetry (persisting across multiple daily reports) that are not yet documented in the Known Channel Pages Failure Patterns table. Root causes are unconfirmed — all are low-volume (1 occurrence each) and require manual investigation before the "Expected?" column can be finalized.
