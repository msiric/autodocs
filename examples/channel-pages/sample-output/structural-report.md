---
date: 2026-03-03
files_checked: 96
missing_files: 0
undocumented_files: 155
---
# Structural Report — 2026-03-03

## Missing Files (referenced in doc, not in repo)

No missing files — all 96 referenced paths verified.

## Undocumented Files (in repo, not in doc)

These files exist under feature-relevant paths but are not referenced
in any documentation. Consider adding them to the doc's file index.

### Channel Pages-specific packages (12 files)

These are in packages owned entirely by Channel Pages and should be
prioritized for documentation.

| Path | Relevant Prefix |
|------|----------------|
| `packages/apps/apps-channel-pages/src/lazy-app.ts` | `packages/apps/apps-channel-pages/` |
| `packages/components/components-channel-pages-hooks/src/fluid-duplicated/constants.ts` | `packages/components/components-channel-pages-hooks/` |
| `packages/components/components-channel-pages-hooks/src/permissions/recipients/get-private-channel-file-recipients.ts` | `packages/components/components-channel-pages-hooks/` |
| `packages/components/components-channel-pages-hooks/src/permissions/recipients/get-shared-channel-file-recipients.ts` | `packages/components/components-channel-pages-hooks/` |
| `packages/components/components-channel-pages-hooks/src/permissions/recipients/get-standard-channel-file-recipients.ts` | `packages/components/components-channel-pages-hooks/` |
| `packages/components/components-channel-pages-modals/src/error/types.ts` | `packages/components/components-channel-pages-modals/` |
| `packages/components/components-channel-pages-modals/src/graphql/components-channel-pages-modals-channel-members-query.graphql` | `packages/components/components-channel-pages-modals/` |
| `packages/components/components-channel-pages-modals/src/graphql/components-channel-pages-modals-file-permissions-query.graphql` | `packages/components/components-channel-pages-modals/` |
| `packages/components/components-channel-pages-modals/src/graphql/components-channel-pages-modals-file-permissions-warning-query.graphql` | `packages/components/components-channel-pages-modals/` |
| `packages/components/components-channel-pages-modals/src/graphql/components-channel-pages-modals-shared-channel-teams-query.graphql` | `packages/components/components-channel-pages-modals/` |
| `packages/components/components-channel-pages-modals/src/paste-loop-modal/types.ts` | `packages/components/components-channel-pages-modals/` |
| `exp-configs/react-web-client/channelPages/fluid.json` | `exp-configs/react-web-client/channelPages/` |

### Shared package: components-fluid (89 files, first 200 of 587 checked)

These files are in the shared Fluid package. Only files relevant to
Channel Pages rendering would typically be documented.

| Path | Relevant Prefix |
|------|----------------|
| `packages/components/components-fluid/fluid-scenario-helpers.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/commands/fluid-coach-marker-commands.tsx` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/commands/fluid-convert-compose-to-loop.tsx` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/common/components/inline-loop-link.tsx` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/component-utils/cleanup-compose-after-action.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/component-utils/create-populated-fluid-code-block.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/component-utils/create-populated-loop-from-draft-content.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/component-utils/get-meeting-url-for-redirect.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/component-utils/is-fluid-status-fatal-for-appending.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/component-utils/try-append-component-from-action.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/component-utils/try-create-populated-component-from-action.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/compose/fluid-compose-container.tsx` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/compose/fluid-compose-import.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/compose/fluid-paste-container.tsx` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/compose/layout/fluid-paste-context-helper.tsx` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/compose/layout/use-fluid-compose-context.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/compose/layout/use-fluid-embed-paste-context.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/compose/layout/use-fluid-paste-context.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/compose/lazy-fluid-compose-container.tsx` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/compose/lazy-fluid-paste-container.tsx` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/compose/use-fluid-send-handler.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/compose/wrap-fluid-content.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/compose/write-fluid-link-changed-util.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/constants.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/embed/fluid-embed-deserializer.tsx` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/embed/fluid-embed-detection-extension.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/embed/fluid-embed-utilities.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/embed/process-fluid-embed-message.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/error/components-fluid-error.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/error/fluid-error-boundary-fallback-with-graphic.tsx` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/error/fluid-error-boundary-fallback.tsx` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/error/fluid-error-details-map.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/error/fluid-expected-errors.tsx` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/error/fluid-notification-banner.tsx` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/error/interaction-required-error.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/error/use-interaction-required-banner.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/fluid-component-status-reducer.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/fluid-component-status.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/fluid-config-helpers.tsx` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/fluid-conversation-members-helper.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/fluid-helpers.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/fluid-render-options.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/fluid-sharelink-helpers.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/fluid-spo-tenant-settings.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/fluid-type-context.tsx` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/graphql/components-fluid-chat-message-query.graphql` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/fluid-content-helpers.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/fluid-file-chiclet-description.tsx` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/fluid-header-icon.tsx` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/fluid-header-saving-badge.tsx` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/fluid-presence-color-helpers.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/fluid-receiver-coachmark.tsx` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/link-to-channel-page-button.tsx` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/permissions/permissions-helpers.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/permissions/use-failed-recipients-handler.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/permissions/use-file-permissions-warning-data.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/permissions/use-grant-permissions-callback.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/permissions/use-grant-permissions-event.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/permissions/use-handle-file-load-failure.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/permissions/use-latest-file-info.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/permissions/use-on-file-chiclet-permission-loaded.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/permissions/use-on-permissions-warning.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/permissions/use-on-update-permissions.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/permissions/use-permission-timeout.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/permissions/use-permissions-ref.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/permissions/use-permissions-scenario.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/permissions/use-set-grant-permissions-variables.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/permissions/use-should-evaluate-permissions.ts` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/shared-header-v2/compose-shared-header.tsx` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/shared-header-v2/hooks/use-shared-header-base-props.tsx` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/shared-header-v2/meeting-notes-scenarios/calendar-app-shared-header.tsx` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/shared-header-v2/meeting-notes-scenarios/meet-for-work-shared-header.tsx` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/shared-header-v2/meeting-notes-scenarios/meeting-notes-scenarios-base-shared-header.tsx` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/shared-header-v2/meeting-notes-scenarios/meeting-notes-shared-header.tsx` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/shared-header-v2/meeting-notes-scenarios/meeting-recap-shared-header.tsx` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/shared-header-v2/message-shared-header.tsx` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/shared-header-v2/shared-header-container.tsx` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/shared-header/fluid-compose-header-renderer.tsx` | `packages/components/components-fluid/` |
| `packages/components/components-fluid/src/header/shared-header/fluid-shared-header-container.tsx` | `packages/components/components-fluid/` |

Note: `packages/components/components-fluid/` contains 587 files total;
only the first 200 were checked. An additional 387 files were not compared.

### Shared package: data-resolvers-platform-tabs (54 files)

These files are in the shared Platform Tabs resolver package. Only
Channel Pages-specific resolvers would typically be documented.

| Path | Relevant Prefix |
|------|----------------|
| `packages/data/resolvers/data-resolvers-platform-tabs/src/connections/platform-channel-tabs-connection.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/connections/platform-chat-predefined-tabs.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/connections/platform-chat-tabs-connection.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/connections/platform-tabs-navigation.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/platform-tabs-events.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/platform-tabs-mock-data-meeting.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/platform-tabs-resolvers.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/platform-tabs-utils.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/platform-tabs-worker-resolver.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/app-device-permissions/app-device-permission-worker-resolvers.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/app-device-permissions/utils.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/constants.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/mutations/platform-create-tab.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/mutations/platform-migrate-tab-mutation-worker-resolver.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/mutations/platform-remove-tab.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/mutations/platform-update-tab.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/mutations/record-app-cache-eviction-resolver.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/mutations/record-app-cache-instance-resolver.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/mutations/record-tabs-usage.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/mutations/send-external-auth-deeplink.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/queries/channel-is-new-badge-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/queries/get-channel-and-team.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/queries/platform-query-tabs-by-message-id.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/queries/precache-app-list-details-resolver.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/queries/precache-app-list-resolver.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/queries/recent-platform-tabs-query.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/queries/skype-conversation-to-team-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/queries/team-and-channel-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/queries/team-channel-is-new-for-user-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/queries/test-utils.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/subscriptions/external-auth-deeplink-event-worker-resolver.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/subscriptions/platform-tab-event-v2-worker-resolver.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/subscriptions/platform-tabs-connection-event-worker-resolver.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/subscriptions/platform-tabs-event-worker-resolver.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/utilities/add-tab-permission-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/utilities/agents-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/utilities/callable-tab-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/utilities/inbuilt-platform-tabs-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/utilities/installed-apps-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/utilities/instant-tabs-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/utilities/personal-tabs-in-meeting-scope-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/utilities/platform-app-cache-resolver-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/utilities/platform-channel-page-create-tab-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/utilities/platform-legacy-tab-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/utilities/platform-pdf-create-tab-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/utilities/platform-recent-tabs-query-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/utilities/platform-tab-channel-files-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/utilities/platform-tab-instance-id-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/utilities/platform-tab-jitter-delay-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/utilities/platform-tab-mock.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/utilities/platform-tab-naming-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/utilities/platform-tab-set-order-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/utilities/platform-tab-sharepoint-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/utilities/platform-tab-storyline-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/utilities/platform-tabs-crud-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/utilities/platform-tabs-crud/platform-create-tab-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/utilities/platform-tabs-crud/platform-tab-remove-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/utilities/platform-tabs-crud/platform-update-tab-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/utilities/platform-tabs-query-for-app-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/utilities/platform-tabs-query-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/utilities/platform-tabs-resolver-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/utilities/precache-app-list-resolver-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/utilities/query-utils/platform-tabs-mapping-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |
| `packages/data/resolvers/data-resolvers-platform-tabs/src/worker-resolver/utilities/team-scope-helper.ts` | `packages/data/resolvers/data-resolvers-platform-tabs/` |

## Summary

- Files checked: 96
- Missing from repo: 0
- Undocumented in docs: 155 (12 in Channel Pages-specific packages, 89 in components-fluid, 54 in data-resolvers-platform-tabs)
- Note: test files, config files (jest.config.js, tsconfig.settings.json, package.json), style files (.styles.ts), interface files (.interface.ts), index files, and owners.txt were excluded from the undocumented count as boilerplate.
- Note: `packages/components/components-fluid/` has 587 files total; only the first 200 were checked (387 unchecked).
