> Archived on 2026-10-21. Historical web/clinical platform material; superseded by the
> personal CLI direction. Completion and test statements below describe past work only.
> See the [archive index](../README.md) before reusing any requirements or commands.

# Live Sidebar Data Design

## Goal

Make the authenticated application sidebar represent the seeded demo data stored in Docker Postgres rather than the legacy frontend mock values.

## Design

`AppSidebar` will fetch the current user, dashboard counts, and sweeps through the existing API client. The organization and user labels will come from `/auth/me`; findings and review badges will come from `/dashboard`; the active sweep link and live state will come from `/sweeps`. Existing loading states will render neutral labels/badges, and API failures will preserve the shell with empty fallback values rather than reintroducing mock data.

No backend schema or seed data changes are required. The dashboard page already uses these same API-backed endpoints and remains unchanged.

## Verification

- Confirm no `mock-data` import remains in the application shell.
- Run the frontend lint and production build.
- Verify the live API endpoints return data with the seeded demo login/session.
