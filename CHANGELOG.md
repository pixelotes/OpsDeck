# Changelog

All notable changes to OpsDeck will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Jira Assets sync**: one-way import from Jira Service Management Assets under Settings > Jira Assets Sync (`settings` module). Each profile selects a Jira object type (by id or name) plus an optional AQL filter, says whether the objects become hardware assets or suppliers, and maps the values of a Jira status attribute to OpsDeck states (asset status or archived; supplier active or archived), with a "Load values from Jira" helper that lists the values in use. New objects are imported once with a few fields (assets: name, serial number, brand and model, created if missing, assignee, order date; suppliers: name, website, email, phone, owner, critical flag); people are matched to OpsDeck users by email or unique full name. Existing records are linked first (assets by serial number, suppliers by name) instead of duplicated. After that **only the state follows Jira**: asset status and archived flag, supplier archived and critical flags, with asset history entries and audit log records. Objects whose status maps to archive are not imported, unmapped values are left unchanged and reported, and records that leave the query are reported, never archived. "Sync now" shows a preview and applies only on confirmation (refusing if Jira changed in between); profiles can also run every N hours (checked every 15 minutes), abort without changes and email the admins when a scheduled run would archive more than a threshold of linked records, and keep a run history. Also `flask jira-assets-sync [--profile] [--dry-run] [--force]`. Uses the Atlassian API connector's site URL, email and API token against `https://api.atlassian.com/jsm/assets/...` (site URLs other than `https://<site>.atlassian.net` are refused). Migration 029
- **Supplier review questionnaires**: periodic supplier reviews are now a structured questionnaire filled in by the supplier's owner (the user, or any member of the owner group) instead of free text. The default template has two checks (is the supplier still active? is it critical?) and seven points answered OK / Not OK / N/A with a comment (issues, certifications, price increases, T&C changes, data breaches, SLAs, other); a Not OK needs a comment. Answers update the supplier: the critical flag follows the check, an inactive supplier skips the review points and can be archived, and the next review date moves forward by the supplier's new **review interval** (3, 6, 12 or 24 months, set on the supplier form). Reviews open automatically two weeks before they are due and the owner is emailed, with weekly reminders once overdue (daily job at 8:30, also `flask schedule-supplier-reviews`); owners see them on My Dashboard and under My Supplier Reviews, and can start one by hand from the supplier page. Templates are editable under Compliance > Supplier Review Templates; completed reviews keep a copy of the questions they were answered with. Reviews are `SecurityAssessment` records, so compliance rules and audits keep working: scheduled reviews that are not filled in no longer count as evidence, and a supplier assessment rule can now require **every active critical (or every active) supplier** to have been reviewed within its frequency. Migration 027
- **API Connectors in core**: the Google Workspace, Microsoft 365, GitHub, JumpCloud, Atlassian and AWS connectors move from the Enterprise plugin into OpsDeck, under Settings > API Connectors (`settings` module permissions). Each connector polls its endpoints on its own interval (checked every 5 minutes), stores every run as a report and diffs it against the previous one; reports can be browsed, compared and opened full screen, and are available as the "Connector Report" source of User Access Reviews (formerly "Enterprise Report"). One disabled connector per service is seeded by `seed-db-prod` (also `flask seed-connectors`). Migration 025 renames the plugin's `enterprise_tasks`/`enterprise_subtasks`/`enterprise_reports` tables to `connector_*`, keeping existing credentials and history, and updates saved UAR comparisons. Fixed on the way: the Microsoft 365 connector was seeded but could not run, the full-screen report view had no route, the connector screens had no permission checks, and seeded connectors carried placeholder credentials that let an unconfigured connector be run. Requires opsdeck-enterprise 0.2.0 or later, which drops its copy of the connectors
- **Microsoft Entra ID user sync**: pull-based sync (Microsoft Graph, client-credentials) of the transitive members of one or more Entra groups, configured under Administration > Entra ID Sync and disabled by default. Users are matched by Entra object id, then by `userPrincipalName` the first time; missing users are created with a configurable default role and no password; name, department, job title and manager are kept in sync; Entra-linked users that leave the scope or are disabled are archived (never deleted) and unarchived if they return, while accounts never linked to Entra are left alone. "Sync now" shows a dry-run preview (create/update/archive/unarchive with per-user changes) and applies only on confirmation, refusing if Entra changed in between. Optional schedule (daily at HH:MM or every N hours); scheduled runs abort without changes and email admins when they would archive more than a threshold (default 10%) of synced users, and a group that cannot be read aborts the run instead of archiving its members. Every run is recorded in a history table and the audit log. Also available as `flask entra-sync [--dry-run] [--force]`. Needs the Graph application permissions `User.Read.All` and `GroupMember.Read.All`
- **Sign in with Microsoft (Entra ID)**: optional single-tenant SSO alongside Google, enabled by `AZURE_OAUTH_CLIENT_ID`, `AZURE_OAUTH_CLIENT_SECRET` and `AZURE_OAUTH_TENANT_ID` (multi-tenant values such as `common` are rejected). Users are matched to existing accounts by `userPrincipalName`, never by the admin-editable `mail` attribute, and the Entra object id is stored on first sign-in (new `user.entra_oid` column, migration 024, shared with the user sync) and trusted from then on. Archived users are refused. Both SSO callbacks now share one post-authentication helper; Google sign-in behaves as before
- **Roadmaps**: New module for strategic planning of goals and initiatives over periods (typically quarters), with its own RBAC permissions. A roadmap holds ordered periods, colour-coded goals as swimlanes, and initiatives placed on a quarter-granularity grid (four draggable steps per period). The timeline view supports dragging to move, resizing, drawing finish-to-start dependencies between initiatives, reordering and moving initiatives between goals, per-period story-point totals, critical-path highlighting, a today marker, search and status filters, and a compact mode. Dependent initiatives are rescheduled automatically when a predecessor moves — a converging dependency is placed by its latest predecessor — and dependency cycles are rejected. Each initiative also has a full detail page (status, priority, progress, story points, owner, ticket reference, markdown description, dependencies both ways, custom fields), and a roadmap can be exported to CSV
- **Service Requests**: New Operations module to submit and track service requests (access, hardware, software, information) through a triage-based fulfillment workflow (Pending → Triage → In Progress → Completed → Closed, with Cancelled as an off-flow state). Includes optional targets (service/asset/software), tags, evidence attachments, a status timeline, and the now-active "Create a Request" quick action on My Dashboard
- **My Tickets on My Dashboard**: New card listing tickets you opened (incidents, changes, requests), limited to those still open or closed within the last 15 days, each with a status badge
- **Service Requests API**: `GET`/`POST /api/v1/requests` (list, detail, and upsert by `external_ref`)
- **Suppliers & Contacts API**: read-only `GET /api/v1/suppliers` and `GET /api/v1/contacts` (list and detail)
- **Changes API reads**: `GET /api/v1/changes` and `GET /api/v1/changes/{id}` (previously POST-only)
- **Models management screen**: Dedicated Core Inventory screen to list, create, edit, and delete asset models across brands, with menu access below Brands
- **Model detail page**: lists the assets and peripherals using a given model; the brand detail page now also lists the brand's assets and peripherals (and links each model to its detail)
- **Status timeline on incident detail**: incidents now show the same step timeline as changes and requests (Investigating → Contained → Resolved → Closed), unifying the ticket detail look — no data model change
- **Subscription spend in the Spend Analysis report**: recurring subscription cost is now reconstructed from billing history — each past billing occurrence is valued at the price and seat count effective on that date (from CostHistory) — and shown alongside one-off purchases, with a "Spend by Month (EUR)" summary. Defaults to the trailing 12 months when no date range is given

### Changed
- **Microsoft Graph access is shared** between the Microsoft 365 API connector and the Entra ID user sync (`src/connectors/msgraph.py`): one token client, with expiry-aware caching and error messages that never echo secrets. A Microsoft 365 connector task can now **use the server's Entra ID app registration** (the `AZURE_OAUTH_*` settings) instead of its own tenant/client/secret, so no Microsoft secret is stored in the database at all
- In-app JSON endpoints now refuse in JSON rather than redirecting to the login page, and this no longer depends on `/api/` appearing in the URL. An endpoint declares that it answers with JSON, so an unauthenticated request gets a `401` with a JSON body and a session that lacks the governing module gets a `403` — previously only the authentication half was covered, and only for endpoints whose path happened to follow the naming convention, which left 33 of them redirecting. Affects the fetch/XHR endpoints behind search, drift detection, the renewal calendar, onboarding pickers, the hiring board, framework controls, incident timelines and similar: an expired session or a missing permission arrived at those callers as HTML that they parsed as if it were data, so the failure was silent. Browser navigation still redirects as before, and the routes that legitimately serve both a form and AJAX (creating a brand or model) answer each caller in its own language
- The `404`, `403`, `429` and `500` error pages also answer JSON for a JSON caller. `abort(404)` on a missing row was otherwise a second route to the same problem: the caller received an HTML error page and parsed it as its payload
- Subscription seat changes made from the subscription page (add / add-all / remove user) now record a CostHistory entry for per-user plans, so historical spend stays accurate
- **Spend Analysis** totals are now normalised to EUR (previously summed mixed currencies as if EUR)
- **My Dashboard "Your Pending Tasks"** now lists only items assigned to you; the notification bell and the My Tasks counter likewise show only assigned items (incidents, changes, requests) — never tickets you opened
- Grouped the three ticket types (Changes, Requests, Incidents) together in the sidebar
- Cache static assets aggressively with mtime-based cache busting, and relaxed API rate limits
- Disposal records now link their disposal partner to a Supplier record (previously free text), shown as a link on disposal/asset/peripheral detail. Migration backfills the link by matching the existing text to a supplier name; unmatched values are not preserved
- **Renewal Calendar**: Replaced FullCalendar (v6) with SimpleCalendarJS. FullCalendar v7 dropped its global/IIFE bundle in favor of ESM-only builds, which our static-asset pipeline (script-tag based, no bundler) can't consume, and v6 has had no updates since December 2024. SimpleCalendarJS is a maintained, zero-dependency, script-tag-compatible alternative with a comparable feature set
- **Supplier owner**: suppliers can now have an internal owner — a user or a group — accountable for the relationship (SRM). Set from the supplier form, shown on the supplier list and detail page, exposed in the suppliers API (`owner_type`, `owner_id`) and importable from CSV through a new optional `owner` column (an active user's email or a group name). An owner who is archived later is kept on edit instead of being silently dropped. This is the groundwork for periodic supplier reviews assigned to each owner
- **Unified list views**: every list table now renders people, empty cells and row actions through one shared component (`components/list_macros.html`). Users and groups show as an initials avatar (or group icon) plus full name linked to their detail page; empty values are a single muted `—` instead of a mix of `N/A`, `-`, `Unassigned` and `Unknown`; row actions are icon-only outline buttons in a fixed order (view, edit, module actions, delete in red), right-aligned under an `Actions` header, with every destructive action going through the confirmation dialog. Lists whose name already linked to a detail page gained an explicit View button
- Updated Node dependencies: @fortawesome/fontawesome-free, mermaid, simple-datatables, suneditor, swagger-ui-dist, tom-select (patch/minor bumps)
- **PostgreSQL driver switched from psycopg2 to psycopg 3** (`psycopg[binary]`). SQLAlchemy 2.1, which Flask-SQLAlchemy now resolves to, uses psycopg 3 for plain `postgresql://` URLs, so a fresh install could no longer connect to the database with the URLs the Helm chart and docs use
- Security updates: PyJWT 2.14.0 (CVE-2026-102268, critical) and WeasyPrint 70.0 (CVE-2026-106443)
- Updated Python dependencies: APScheduler, pytz, Markdown, slack_sdk, cryptography, boto3 (patch/minor bumps)

### Fixed
- **API connector credentials were stored in plaintext.** Client secrets, AWS secret keys, API and access tokens and Google service-account keys in `connector_tasks.auth_config` were readable by anyone with database or backup access. They are now encrypted at rest (Fernet) with `DATA_ENCRYPTION_KEY`, or a key derived from `SECRET_KEY` when that is unset; migration 026 encrypts existing values, and `flask rotate-data-encryption-key` re-encrypts them after setting or rotating the key. The security check reports when no dedicated key is configured
- The supplier edit form showed empty optional fields (address, website, notes, compliance notes) as the text `None`, and saving the form stored that text
- **Universal Search returned records the user had no access to.** Search applied no module permission check at all, so any signed-in user could read the description of a UAR finding, the title of a security incident or a vendor's notes through the search box without holding compliance, operations or procurement. Results and facet counts are now filtered by the modules the user can read, on both the full search page and the quick search box in the header — an entity type that is not classified is excluded rather than shown
- **Universal Search answered `500` for every query.** One of the searchable fields on business services pointed at a related object rather than a column, and matching against it raised an error; since business services are searched by default, the search page failed for everyone regardless of the query
- **Custom field values were re-read from the database once per field, and once per user in the access-review export.** Templates ask for each custom field in turn, which cost two queries apiece — sixteen to display eight fields on an asset — and the access-review user export repeated that for every active user, so its cost grew with the size of the user table (a thousand queries for five hundred users). Both now cost two queries in total. Affects the asset, peripheral, user and initiative detail and edit pages, and the user export
- **Access reviews could not use an Enterprise Report as a data source.** The call into the review engine was missing an argument and passed the report itself where a table name was expected, so selecting that source failed outright; and once called correctly it reported the dataset as empty, because the loaded rows were not passed back for the execution's row count. Only affects deployments running the Enterprise plugin
- Evidence download links on change and request detail pages (used the filename instead of the attachment id, causing a routing error)
- Status timeline line now runs through the centre of the step circles on change and request detail pages

## [0.6.10] - 2026-06-03

### Added
- **Google Users Import**: Helper script to import users from Google, with accompanying scripts and READMEs

### Changed
- Updated Python and Node dependencies
- Helm chart deployment strategy set to `Recreate` to avoid PVC conflicts on upgrade (volumes are ReadWriteOnce and cannot be shared between pods)

### Fixed
- UAR automations: date type mismatch, plus execution against Subscription and Business Service sources
- Risk assessment evidence picker showed document IDs instead of names
- Robot icon not centered in the Automation Rules empty state on control detail

## [0.6.9] - 2026-05-14

### Added
- **Hardware Brands as Objects**: Manage brands as first-class entities, with a brand breakdown in reports and a new assets dashboard graph
- **CMDB ↔ Services**: Attach configuration/CMDB items to business services
- **Onboarding/Offboarding Notes**: Add notes to onboarding and offboarding processes
- **IRSA Support**: IAM Roles for Service Accounts (AWS)
- **Backup Image & Cronjob**: Dedicated backup container image plus a backup cronjob in the Helm chart
- **Custom Sender Name**: Configurable email sender name
- **Migration Test Suite**: Added migration tests and refactored the migration system
- **Dependency Graph Labels**: Labels on the dependency graph

### Changed
- Suppliers are now optional on subscriptions
- Credentials truncated to 12 characters in display
- Services and users ordered alphabetically
- Removed legacy CRM module references
- Offboardings can be closed without 100% completion
- Flask no longer runs in debug mode (security scan fix)

### Fixed
- 403 when revoking access from services
- Offboardings: service transfer and the transfer-service button not showing
- Empty brands dropdown in peripherals
- Crash when attaching a file to a service
- Asset crash on null data
- API pagination
- Notification jobs
- Sticky tabs and assorted layout issues
- Service context tab not showing in the service detail view
- Evaluations template and missing route names

## [0.6.8] - 2026-02-20

### Added
- **Critical Suppliers**: Flag suppliers as critical with badge visibility across lists and detail views
- **Assessments History**: Moved assessments under Vendor Compliance as a sub-page
- **SOA at Framework Level**: SOA applicability fields on controls, inherited by new audits, with change visualization in framework reports
- **Status Filters**: Dropdown filters for Change Management (Draft, Pending Approval, Approved, In Progress, Completed) and Security Incidents (Investigating, Contained, Resolved, Closed)
- **API Upsert Endpoints**: POST endpoints with `external_ref` support for external integrations
- **Org Chart**: Replaced Mermaid.js with orgchart.js for better organizational rendering
- **Client-side Pagination**: Added to several tables that were missing it
- **Skeleton Loaders**: Deployed across additional pages

### Changed
- Compliance Dashboard moved to the Compliance menu section with proper RBAC permissions
- Vendor Compliance table now shows Critical status and Last Assessment date instead of GDPR/Assessment dates
- Full description shown for linked evidence items in framework control details (previously truncated)
- Gunicorn configured as production WSGI server
- SQLAlchemy `pool_pre_ping` enabled for connection resilience
- EasyMDE removed from global load (lazy-loaded where needed)
- Back button added to custom error pages
- Database indexes added for query performance
- Replaced bare `except:` clauses with `except Exception:`

### Fixed
- Timezone-aware datetime errors in compliance rule evaluations
- Static assets (CSS/JS) no longer count towards rate limits
- Entrypoint migration logic now walks the chain revision-by-revision instead of stamping head blindly
- Slow queries on health dashboard
- Menu losing active state when browsing
- Dark mode: owner badges and change title text now readable
- Mobile sidebar auto-hide behavior
- Archived items filter not working correctly
- Internal routes exposed without authentication
- Empty manager/buddy fields on new user creation
- Duplicate blueprint registration in admin module
- Flash message severity types
- Debug-level log messages corrected to info level
- Translated remaining Spanish strings to English
- Test assertions updated to match current flash messages

## [0.6.7] - 2026-02-10

### Added
- **Audit Log**: Comprehensive audit trail for security-relevant actions
- **Defense Packs**: Improved defense pack templates and management
- **Procurement Module Overhaul**: Redesigned subscription and procurement workflows

### Fixed
- Write permissions for core inventory module
- Subscription cost calculations and validation
- Simple Datatables JS path resolution

## [0.6.6] - 2026-02-05

### Added
- **Toast Notification System**: Modern toast notifications with smooth animations
  - Auto-converts Flask flash messages to toasts
  - 5 notification types: success, error, warning, info, danger
  - Auto-dismiss after 4 seconds (configurable)
  - Responsive design for desktop and mobile
  - Maximum 5 simultaneous toasts
  - Close button and keyboard support
- **Empty State Component**: Reusable empty state component for better UX
  - Friendly messages when no data is available
  - Customizable icon, title, message, and action buttons
  - Fade-in animations for smooth appearance
  - Fully responsive with mobile optimizations
  - Example implementation in Assets list view
- **Skeleton Loaders**: Content placeholders during data loading
  - Multiple skeleton types: table, card, list, dashboard, and custom
  - Smooth shimmer animation with gradient effect
  - Alternative animations: pulse and wave effects
  - Reusable template components for common use cases
  - JavaScript utilities for easy integration
  - `Skeleton.show()` and `Skeleton.hide()` for manual control
  - `Skeleton.wrap()` for automatic loading state management
  - Responsive adjustments for mobile devices
  - Dark mode support
- **Collapsible Sidebar**: Intelligent sidebar with hover reveal on desktop
  - Toggle button to collapse/expand sidebar
  - Hover reveal when collapsed (desktop only)
  - Persistent state saved in localStorage
  - Smooth CSS transitions with cubic-bezier animations
  - Main content expands when sidebar is collapsed
- **Mobile Sidebar**: Full responsive behavior for mobile devices
  - Overlay with semi-transparent background
  - Tap outside or press ESC to close
  - Smooth slide-in/slide-out animations
- **Accessibility Improvements**:
  - Skip to main content link for keyboard navigation
  - Focus visible states with purple outline
  - ARIA labels on interactive elements
  - Keyboard support (ESC to close modals/sidebar)
- **Button Microinteractions**: Enhanced button feedback and animations
  - **Ripple Effect**: Material Design-inspired ripple animation on click
  - Hover effects with subtle elevation and color-specific shadows
  - Active state feedback with reduced elevation
  - Loading state with spinner animation
  - Shake animation for error states (e.g., form validation)
  - Pulse animation for important CTAs
  - Smooth color transitions (0.15s)
  - Icon scaling and rotation on hover
  - Disabled state handling
  - Automatic initialization for dynamically added buttons
  - Global utility functions: `ButtonEffects.shake()`, `ButtonEffects.pulse()`, `ButtonEffects.setLoading()`

### Changed
- Updated CSS architecture with better organization and comments
- Improved z-index hierarchy for proper layering
- Enhanced mobile responsive breakpoint handling (768px)
- **Sidebar Toggle Redesign**: Replaced floating button with integrated handlebar
  - Handlebar attached to sidebar edge (moves with sidebar)
  - 15px wide × 60px tall vertical bar with visible grip dots
  - Smooth hover animation (expands to 18px)
  - Grip dots with 0.7 opacity for better visibility
  - Hidden on mobile (uses navbar hamburger button instead)
  - Better visual integration and professional appearance
- **Frontend Consistency Improvements**: Applied new components globally
  - Empty state component now used in Credentials, Certificates, Subscriptions, and Budgets lists
  - Skeleton loaders added to Ops & Finance Dashboard and Compliance Dashboard
  - Global form submission loading states with automatic button spinners
  - Toast notifications already auto-convert all Flask flash messages

### Fixed
- **Timezone Variable Shadowing**: Fixed UnboundLocalError in message queue processing
  - Fixed variable shadowing in `src/notifications.py` (lines 450, 560)
  - Fixed variable shadowing in `src/services/search_service.py` (line 398)
  - Fixed variable shadowing in `src/services/compliance_drift_service.py` (line 427)
  - Renamed local `now` variables to `current_time` to avoid conflicts with timezone helper function
- **MaintenanceLog Timezone Inconsistency**: Fixed mixed timezone handling in MaintenanceLog.updated_at
  - Fixed `onupdate=datetime.utcnow` to use `onupdate=lambda: now()` for consistency
  - Ensures all datetime updates use timezone-aware helpers (src/models/assets.py:430)
- **Collapsible Sidebar Issues**: Fixed sidebar toggle button and hover reveal
  - Toggle button now positioned below navbar (top: 70px) with correct z-index (1021)
  - Implemented JavaScript-based hover reveal when mouse is near left edge (0-10px)
  - Sidebar smoothly reveals on edge hover and hides after 300ms delay when mouse leaves
- **Personal Dashboard Language**: Translated personal dashboard from Spanish to English
  - All labels, messages, and empty states now in English
  - Consistent with rest of application language
- **Dashboard CSS Loading**: Fixed personal dashboard not loading CSS (incorrect block name)
- **Enterprise Plugin Permissions**: Fixed unauthorized access to enterprise plugin menu
- **None Value Handling**: Fixed TypeError when subscriptions have no renewal date
  - Fixed in organizational health dashboard (line 570)
  - Fixed in ops & finance dashboard (line 971)
  - Added None checks before date comparisons
- **Credentials Timezone Awareness**: Fixed TypeError in credentials expiry calculations
  - Fixed naive/aware datetime comparison in `is_expired` property (line 185)
  - Fixed naive/aware datetime subtraction in `days_until_expiry` property (line 194)
  - Added `to_utc()` conversion for database datetime fields before comparison with `now()`

### Technical
- New file: `src/static/js/toast.js` - Complete toast notification system (190 lines)
- New file: `src/static/js/button-effects.js` - Button microinteractions and ripple effects (150 lines)
- New file: `src/static/js/skeleton.js` - Skeleton loader utilities (250 lines)
- New file: `src/templates/components/empty_state.html` - Reusable empty state component
- New file: `src/templates/components/skeleton_table.html` - Table skeleton loader
- New file: `src/templates/components/skeleton_card.html` - Card skeleton loader
- New file: `src/templates/components/skeleton_list.html` - List skeleton loader
- New file: `src/templates/components/skeleton_dashboard.html` - Dashboard skeleton loader
- Updated: `src/static/css/custom.css` - +680 lines of new styles (skeletons, empty states, buttons, animations)
- Updated: `src/templates/layout.html` - Integration of all new JS modules
- Updated: `src/templates/assets/list.html` - Example empty state implementation
- New documentation: `docs/FRONTEND_IMPROVEMENTS.md`

## [0.6.5] - 2026-02-04

### Added
- **Timezone Helper Module**: Complete timezone-aware datetime implementation
  - New `src/utils/timezone_helper.py` with `now()`, `today()`, `to_local()`, `to_utc()` helpers
  - Configurable timezone via `TIMEZONE` environment variable (default: 'Europe/Madrid')
  - All datetime operations now DST-aware using pytz
  - 18 comprehensive tests verifying winter/summer time transitions
- **Automated UAR (User Access Review)**: Schedule and automate access reviews
  - Email notifications when findings exceed configured thresholds
  - "UAR Alert - Findings Detected" email template
  - Per-comparison recipient configuration
  - New dashboard at `/compliance/uar/automation`
- **Compliance Drift Detection**: Automated compliance regression monitoring
  - Daily snapshots at 9:00 AM UTC via APScheduler
  - Email alerts to admins when compliance regressions detected
  - "Compliance Drift Alert" email template
  - New dashboard at `/compliance/drift/dashboard`
  - ComplianceAudit model extended with drift tracking

### Changed
- Migrated ALL 141 datetime/date calls across 37 files to use timezone helpers
- Menu updates: Added "UAR Automation" and "Drift Detection" to Compliance menu
- Email template system enhanced for automated notifications

### Fixed
- **Critical DST Bug**: App now works correctly year-round instead of only 6 months
- Date/Time handling issues (bugs medio 1, 4, 5)
- Subscription renewal date calculation optimized with mathematical approach
- Budget validity checks clarified with inclusive date semantics
- Negative amount validation in Budget and Subscription models

### Technical
- Added `pytz` dependency for timezone support
- Documentation: `docs/TIMEZONE_USAGE.md`
- Database migration: Extended ComplianceAudit table
  - Added `audit_type` field ('manual' | 'drift_snapshot')
  - Added `snapshot_data` JSON field
  - Made `name` and `framework_id` nullable for drift snapshots

## [0.6.4] - 2025-XX-XX

### Fixed
- Permissions cache test issues
- Unit test stability improvements

### Changed
- Updated WeasyPrint dependency for PDF generation
- Visual standardization across templates

## [0.6.3-4] - 2025-XX-XX

### Changed
- Better error handling for data import operations
- Enhanced logging in permissions service

## [0.6.3-3] - 2025-XX-XX

### Fixed
- Simple Datatables JavaScript file paths

## [0.6.3-2] - 2025-XX-XX

### Fixed
- OAuth scopes configuration

### Added
- Filebeat sidecar container for log aggregation

## [0.6.3-1] - 2025-XX-XX

### Fixed
- Simple Datatables vendor files path resolution

## [0.6.3] - 2025-XX-XX

### Fixed
- SSO login flow issues

### Changed
- Automatic permissions cache refresh on login

## [0.6.2] - 2025-XX-XX

### Fixed
- Permissions caching issues

## [0.6.1] - 2025-XX-XX

### Fixed
- Database table name quoting for PostgreSQL compatibility
- Database environment variable naming

## [0.6.0] - 2025-XX-XX

### Added
- Major feature release (details from git history)

---

For changes in versions prior to 0.6.0, please refer to the git commit history.

---

## Release Process

1. Update this CHANGELOG.md with new version and date
2. Update version in relevant files (if applicable)
3. Commit changes: `git commit -m "chore: release vX.Y.Z"`
4. Create git tag: `git tag -a vX.Y.Z -m "Release vX.Y.Z"`
5. Push changes and tags: `git push && git push --tags`
6. Create GitHub release with changelog excerpt

## Version Numbering

We follow [Semantic Versioning](https://semver.org/):
- **MAJOR** version: Incompatible API changes
- **MINOR** version: New functionality (backwards compatible)
- **PATCH** version: Bug fixes (backwards compatible)

## Categories

- **Added**: New features
- **Changed**: Changes to existing functionality
- **Deprecated**: Soon-to-be removed features
- **Removed**: Removed features
- **Fixed**: Bug fixes
- **Security**: Security vulnerability fixes
- **Technical**: Infrastructure, dependencies, or developer-facing changes

---

[Unreleased]: https://github.com/pixelotes/opsdeck/compare/v0.6.8...HEAD
[0.6.8]: https://github.com/pixelotes/opsdeck/compare/v0.6.7...v0.6.8
[0.6.7]: https://github.com/pixelotes/opsdeck/compare/v0.6.6...v0.6.7
[0.6.6]: https://github.com/pixelotes/opsdeck/compare/v0.6.5...v0.6.6
[0.6.5]: https://github.com/pixelotes/opsdeck/compare/v0.6.4...v0.6.5
[0.6.4]: https://github.com/pixelotes/opsdeck/compare/v0.6.3-4...v0.6.4
[0.6.3-4]: https://github.com/pixelotes/opsdeck/compare/v0.6.3-3...v0.6.3-4
[0.6.3-3]: https://github.com/pixelotes/opsdeck/compare/v0.6.3-2...v0.6.3-3
[0.6.3-2]: https://github.com/pixelotes/opsdeck/compare/v0.6.3-1...v0.6.3-2
[0.6.3-1]: https://github.com/pixelotes/opsdeck/compare/v0.6.3...v0.6.3-1
[0.6.3]: https://github.com/pixelotes/opsdeck/compare/v0.6.2...v0.6.3
[0.6.2]: https://github.com/pixelotes/opsdeck/compare/v0.6.1...v0.6.2
[0.6.1]: https://github.com/pixelotes/opsdeck/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/pixelotes/opsdeck/releases/tag/v0.6.0
