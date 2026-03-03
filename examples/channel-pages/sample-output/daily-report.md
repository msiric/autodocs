---
date: 2026-03-02
sync_status: success
pr_count: 9
channel_pages_prs: 4
mario_reviews: 2
mario_authored: 4
create_reliability: 99.05
load_reliability: 99.82
anomaly_count: 2
---
# Work Report — 2026-03-02

## Team PRs (last 72h)
- PR #1477230: "[Channel Pages] - Surface server response errors from parent exceptions" by Mario Siric — merged
  Channel Pages: YES (packages/components/components-fluid/, packages/data/resolvers/data-resolvers-platform-tabs/)
- PR #1482424: "[Channel Pages] - Elevate tab creation CDL workflow to REALTIME priority" by Mario Siric — merged
  Channel Pages: YES (packages/data/resolvers/data-resolvers-platform-tabs/)
- PR #1486370: "[Channel Pages] - Handle concurrent provision race condition for componentUrl overwrite" by Mario Siric — merged
  Channel Pages: YES (packages/components/components-fluid/)
- PR #1480212: "[Channel Pages] - Add retry for createFluidSnapshot file creation timeout issue" by Mario Siric — merged
  Channel Pages: YES (packages/components/components-fluid/, exp-configs/react-web-client/channelPages/)
- PR #1478877: "[Fluid] Playwright: consolidate and reuse selectors (Part 3)" by Andrei Fateev — merged
  Channel Pages: NO
- PR #1487526: "[Fluid] Playwright: consolidate and reuse selectors (Part 10)" by Andrei Fateev — merged
  Channel Pages: NO
- PR #1484677: "[Fluid] Playwright: consolidate and reuse selectors (Part 7)" by Andrei Fateev — merged
  Channel Pages: NO
- PR #1460999: "[Quoted reply][R18CM] Fix dangling RAF call." by Ryan Vlaming — merged
  Channel Pages: NO
- PR #1475481: "Migrating text-only-title-renderer to Fluent V9" by Magdalini Palaiologou — merged
  Channel Pages: NO

## Mario's Activity
- Reviewed: PR #1478877 (Andrei Fateev), PR #1484677 (Andrei Fateev)
- Authored/Merged: PR #1477230, PR #1482424, PR #1486370, PR #1480212

## Telemetry Summary
| Scenario | Total | Failures | Rate | Users |
|----------|-------|----------|------|-------|
| fluid_load_channel_page | 110364 | 204 | 0.18% | 51930 |
| fluid_create_channel_page | 28715 | 272 | 0.95% | 18791 |
| fluid_link_channel_page | 5775 | 7 | 0.12% | 3948 |
| fluid_link_loop_from_message_to_channel | 83 | 4 | 4.82% | 51 |

### Error Breakdown
- fluid_create_channel_page: ApolloError fetching tab data (99), failed to create tab (67), snapshot parse error 0x200 (24), RequireStatusFailed (21), EPM getDriveId 429 (20), overwrite componentUrl (13), TimedOut (10), EPM getSiteInfo undefined/503 (8), ODSP throttling 429 (5), Could not get iframe (4), API text/plain 429 (3), tab update failed (3), EPM acquireToken/auth errors (4), Name already exists (2), Entry point not Fluid module (1), Invalid request (1), Summary required (1), failed to download script (1), refresh token expired (1), EPM getDriveId 400 (1), API verbose JSON 200/0 (1), snapshot Invalid code 101 (1), Name collides (1)
- fluid_load_channel_page: ODSP throttling 429 (83), ApolloError fetching tab data (73), snapshot parse error 0x200 (9), fetchTokenError/auth (7), ODSP 503 (2), Platform tab not ChannelPageTab (2), Entry point not Fluid module (1), Path too long 400 (1)

### Anomalies
- NEW: "Error parsing snapshot response: Invalid code: 101" in fluid_create_channel_page (1 occurrence, 1 user) — not matching any known pattern in telemetry-guide.md; persisting from previous report
- NEW: "Entry point of loaded package not a Fluid module. Trying to load ContainerType: @fluidx/loop-page-container" in fluid_load_channel_page (1 occurrence) and fluid_create_channel_page (1 occurrence) — not previously observed
- fluid_link_loop_from_message_to_channel failure rate 4.82% (4/83) — low volume but elevated; continuing from previous report
- Retry storms: none detected (0 users with >10 failures)

## Context File Suggestions
- PR #1477230 touches error handling in components-fluid — "RequireStatusFailed" errors (21 occurrences) now expected to surface as out-of-storage UI
- PR #1486370 addresses componentUrl overwrite race condition — "overwrite componentUrl" errors (13 occurrences) should decrease as fix propagates
- PR #1480212 adds retry for file creation timeout — "TimedOut" errors (10 occurrences) should decrease once `enableChannelPagesFileCreationRetry` flag is enabled
- PR #1482424 elevates CDL priority to REALTIME — may reduce "failed to create tab" errors (67 occurrences) caused by workflow starvation
