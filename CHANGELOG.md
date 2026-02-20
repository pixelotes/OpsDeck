# Changelog

All notable changes to OpsDeck will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.6.8] - 2026-02-20

### Added
- **SOA at Framework Level**: SOA applicability fields on controls, inherited by new audits, with change visualization in framework reports
- **Status Filters**: Dropdown filters for Change Management (Draft, Pending Approval, Approved, In Progress, Completed) and Security Incidents (Investigating, Contained, Resolved, Closed)
- **API Upsert Endpoints**: POST endpoints with `external_ref` support for external integrations
- **Org Chart**: Replaced Mermaid.js with orgchart.js for better organizational rendering
- **Client-side Pagination**: Added to several tables that were missing it
- **Skeleton Loaders**: Deployed across additional pages

### Changed
- Gunicorn configured as production WSGI server
- SQLAlchemy `pool_pre_ping` enabled for connection resilience
- EasyMDE removed from global load (lazy-loaded where needed)
- Back button added to custom error pages
- Database indexes added for query performance
- Replaced bare `except:` clauses with `except Exception:`

### Fixed
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
