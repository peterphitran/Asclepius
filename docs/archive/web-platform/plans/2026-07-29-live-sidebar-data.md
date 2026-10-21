> Archived on 2026-10-21. Historical web/clinical platform material; superseded by the
> personal CLI direction. Completion and test statements below describe past work only.
> See the [archive index](../README.md) before reusing any requirements or commands.

# Live Sidebar Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the application sidebar’s legacy mock values with authenticated API data from the seeded Postgres-backed backend.

**Architecture:** Keep the existing `api` client and fetch the current user, dashboard counts, and sweeps in `AppSidebar`. Render safe loading/empty states while requests resolve, and use the existing token/error behavior without changing backend contracts.

**Tech Stack:** Next.js 16, React 19, TypeScript, existing FastAPI API client.

## Global Constraints

- Do not change backend schemas, seed data, or existing user-facing dashboard data flow.
- Do not modify unrelated user changes already present in the worktree.
- Do not use `mock-data.ts` for live application-shell values.

### Task 1: Add sidebar live-data loading

**Files:**
- Modify: `frontend/src/components/app-sidebar.tsx`

**Interfaces:**
- Consumes: `api.me()`, `api.dashboard()`, and `api.sweeps()` from `frontend/src/lib/api.ts`.
- Produces: Sidebar organization, user, counts, and active sweep derived from API responses.

- [ ] **Step 1: Replace mock imports and constants**

Remove the `mock-data` import and add the API types/functions needed for `User`, `Sweep`, and `DashboardStats`.

- [ ] **Step 2: Add a client-side sidebar data effect**

Fetch the three API resources after mount, keep local state for `user`, `dashboardStats`, and `activeSweep`, and select the first running sweep or first returned sweep. Treat failed requests as empty shell data so navigation remains usable.

- [ ] **Step 3: Render loading-safe live values**

Use API-derived values for organization name/plan, user name/email/initials/role, findings and review badges, active sweep URL, and the live badge. Render neutral placeholders while values are unavailable.

- [ ] **Step 4: Run lint to catch TypeScript and hook issues**

Run from `frontend`:

```powershell
npm run lint
```

Expected: exit code 0.

### Task 2: Verify the production build and live API wiring

**Files:**
- Modify: none

- [ ] **Step 1: Build the frontend**

Run from `frontend`:

```powershell
npm run build
```

Expected: exit code 0.

- [ ] **Step 2: Confirm no application-shell mock import remains**

Run from the repository root:

```powershell
rg -n "mock-data" frontend/src/components frontend/src/app
```

Expected: no result for `app-sidebar.tsx`; any remaining result must be outside live application-shell rendering.

- [ ] **Step 3: Check the backend health endpoint**

Run:

```powershell
Invoke-WebRequest http://localhost:8000/health -UseBasicParsing
```

Expected: HTTP 200 with `status: ok`.
