# Settle — Project Specification

> Payment collection infrastructure for Nigerian SMEs and the developers who build for them.

---

## Table of Contents

1. [Overview](#overview)
2. [Users & Roles](#users--roles)
3. [Core Concepts](#core-concepts)
4. [Architecture Principles](#architecture-principles)
5. [Database Schema (ERD)](#database-schema-erd)
6. [Reconciliation Rules](#reconciliation-rules)
7. [API Specification](#api-specification)
   - [Auth](#auth)
   - [Collections](#collections)
   - [Accounts](#accounts)
   - [Transactions](#transactions)
   - [Notifications](#notifications)
   - [Webhooks](#webhooks)
   - [Reports](#reports)
8. [Notification System](#notification-system)
9. [Nomba Integration](#nomba-integration)
10. [Webhook System](#webhook-system)
11. [Edge Cases](#edge-cases)
12. [Out of Scope](#out-of-scope)

---

## Overview

Settle sits on top of Nomba's Virtual Account and Checkout APIs and exposes two interfaces:

- **Dashboard (SME-facing):** A no-code UI where businesses onboard, add customers, provision
  dedicated virtual accounts per customer, and track payments in real time.
- **REST API (Developer-facing):** The same engine exposed as a clean, documented API with API
  key auth and webhook forwarding so developers can build collection products without touching
  Nomba directly.

The frontend itself consumes the REST API — proving the developer experience in production.

---

## Users & Roles

| Role | Description |
|---|---|
| **Tenant** | A business that signs up on Settle (landlord, school, cooperative, freelancer). Has a dashboard account, an API key, and owns all their customers' virtual accounts. |
| **Customer** | A tenant's end-user (a tenant's tenant 😄, a student, a cooperative member). Does not log in to Settle. Identified by `customer_ref`. Can visit a public payment page. |
| **Developer** | May or may not be the same person as the Tenant. Uses the API key to interact programmatically. |

---

## Core Concepts

### Tenant
A business registered on Settle. Has:
- Dashboard login (email + password → JWT)
- API key (for programmatic access)
- Optional webhook URL (Settle forwards payment events here)

### Virtual Account
A dedicated Nomba-provisioned bank account number assigned to one customer of a tenant.
- Permanent (static) by default
- Optionally locked to an `expected_amount` for exact-payment use cases
- Funds flow to Settle's Nomba parent account; the ledger tracks per-customer balances

### Ledger
An append-only record of credits per virtual account. Used to compute running balance and
generate customer statements.

### Transaction
Every inbound transfer recorded from a Nomba webhook. Always tied to a virtual account
(or flagged as misdirected if no match is found). Carries a reconciliation status.

### Collection
A grouping concept for tenants — e.g. "June Rent 2025" or "2024/2025 School Fees Term 1".
A collection has multiple customers/accounts under it. Useful for bulk provisioning and
reporting.

### Recurring Schedule
An optional billing cycle attached to a **collection**, not an individual account (e.g. "all
accounts in June Rent 2025 are billed monthly"). Every account provisioned under that
collection inherits the schedule automatically. No new virtual account is created per cycle —
the same account is reused, and due/overdue status is derived from `last_paid_at` and
`next_due_date` rather than tracked through a separate billing-period record.

---

## Architecture Principles

These rules apply to every module written for this project. Speed matters more than ceremony,
but these constraints keep the codebase easy to extend without rewrites.

- **Routes are dumb.** Every route handler does: parse/validate input → call one service
  function → return. No business logic, no branching, minimal docstrings (a one-liner is
  enough — implementation quality is what's judged, not documentation).
- **Services own logic.** All business rules, reconciliation, provisioning, and notification
  decisions live in `services/`. Services are the only place allowed to talk to the DB session
  in a non-trivial way.
- **Background tasks are the default for anything non-critical-path.** Webhook forwarding,
  notification dispatch, receipt generation — all fire-and-forget via `BackgroundTasks`. The
  caller never branches on what's configured; it always calls `notify(context)` and the
  manager figures out the rest.
- **Factories isolate things likely to change.** Two factories in this codebase:
  - `NotificationManager` → `get_channel(name)` returns a channel handler (email, sse, webhook).
    Adding SMS later means adding one channel class, touching nothing else.
  - `PaymentProviderClient` → Nomba-specific calls are wrapped behind an interface
    (`create_virtual_account`, `suspend_account`, etc.) so swapping or adding a provider later
    doesn't touch reconciliation or route code.
- **No silent coupling.** A module should not need to know about another module's internals to
  do its job. The reconciliation service doesn't know *how* a notification gets delivered —
  it just builds a context and hands it off.
- **Calendar math uses `python-dateutil`**, never naive `timedelta(days=30)`, anywhere a
  "monthly" or similar human-calendar interval is calculated (see Recurring Schedules).

---

## Database Schema (ERD)

### `tenants`
```
id                UUID        PK
email             VARCHAR     UNIQUE NOT NULL
hashed_password   TEXT        NOT NULL
business_name     VARCHAR     NOT NULL

-- api key: only the hash + prefix are stored, raw key shown once on create/regenerate
hashed_api_key    TEXT        UNIQUE NULL
api_key_prefix    VARCHAR(12) NULL          -- e.g. "sk_live_a1b2" — shown in dashboard for ID

webhook_url       TEXT        NULL          -- where Settle forwards payment events
token_version     INT         DEFAULT 0     -- bump to invalidate all existing JWTs

is_active         BOOLEAN     DEFAULT true
created_at        TIMESTAMPTZ
updated_at        TIMESTAMPTZ
```

### `collections`
```
id              UUID        PK
tenant_id       UUID        FK → tenants.id
name            VARCHAR     NOT NULL        -- e.g. "June Rent 2025"
description     TEXT        NULL
expected_amount NUMERIC     NULL            -- default amount for all accounts in this collection
is_active       BOOLEAN     DEFAULT true
created_at      TIMESTAMPTZ
updated_at      TIMESTAMPTZ
```

### `virtual_accounts`
```
id                   UUID        PK
tenant_id            UUID        FK → tenants.id
collection_id        UUID        FK → collections.id NULL

-- customer identity
customer_name        VARCHAR     NOT NULL
customer_ref         VARCHAR     NOT NULL            -- tenant-assigned unique ref per customer
customer_email       VARCHAR     NULL
customer_phone       VARCHAR     NULL

-- nomba details
nomba_account_ref    VARCHAR     UNIQUE NOT NULL      -- the ref we sent to Nomba
bank_account_number  VARCHAR     NULL                 -- returned by Nomba after provisioning
bank_account_name    VARCHAR     NULL
bank_name            VARCHAR     NULL

-- payment config
expected_amount      NUMERIC     NULL                 -- NULL = accept any amount
description          TEXT        NULL
is_active            BOOLEAN     DEFAULT true
expires_at           TIMESTAMPTZ NULL

-- recurrence (inherited from collection.recurring_schedule, NULL if collection has none)
last_paid_at         TIMESTAMPTZ NULL                 -- set on each exact/overpaid reconciliation
next_due_date        TIMESTAMPTZ NULL                 -- recomputed on creation and on payment

created_at           TIMESTAMPTZ
updated_at           TIMESTAMPTZ

UNIQUE(tenant_id, customer_ref)   -- a tenant cannot have two accounts for the same customer ref
```

### `transactions`
```
id                      UUID        PK
virtual_account_id      UUID        FK → virtual_accounts.id NULL  -- NULL if misdirected
nomba_transaction_ref   VARCHAR     UNIQUE NOT NULL INDEX
nomba_account_ref       VARCHAR     NOT NULL

amount                  NUMERIC     NOT NULL
currency                VARCHAR     DEFAULT 'NGN'
sender_account_number   VARCHAR     NULL
sender_account_name     VARCHAR     NULL
sender_bank_name        VARCHAR     NULL
narration               TEXT        NULL

-- reconciliation
status                  VARCHAR     NOT NULL  -- see reconciliation rules
expected_amount         NUMERIC     NULL
difference              NUMERIC     NULL      -- amount - expected_amount (positive = overpaid)

raw_payload             TEXT        NULL      -- full Nomba webhook JSON for debugging
paid_at                 TIMESTAMPTZ NULL
created_at              TIMESTAMPTZ
```

### `ledger_entries`
```
id                  UUID        PK
virtual_account_id  UUID        FK → virtual_accounts.id
transaction_id      UUID        NULL                -- which transaction triggered this entry
entry_type          VARCHAR     NOT NULL            -- 'credit' | 'debit'
amount              NUMERIC     NOT NULL
running_balance     NUMERIC     NOT NULL            -- balance after this entry
description         TEXT        NULL
created_at          TIMESTAMPTZ
```

### `recurring_schedules`

Recurrence lives on the **collection**, not the individual account. Every account provisioned
under a collection inherits its schedule automatically — there is no per-account recurrence
setup.

```
id                  UUID        PK
collection_id       UUID        FK → collections.id UNIQUE   -- one schedule per collection
frequency           VARCHAR     NOT NULL      -- 'weekly' | 'monthly' | 'custom'
interval_days       INT         NULL          -- used only when frequency = 'custom'
is_active           BOOLEAN     DEFAULT true
created_at          TIMESTAMPTZ
updated_at          TIMESTAMPTZ
```

### Due-date tracking on `virtual_accounts`

No cron job, no daily sweep. Due dates are set reactively and overdue status is **derived at
read time**, never stored — so it can never go stale.

Two extra columns on `virtual_accounts` (added to the table above):
```
last_paid_at        TIMESTAMPTZ NULL   -- set on each qualifying payment
next_due_date       TIMESTAMPTZ NULL   -- recomputed on creation and on each payment
```

**Lifecycle:**
1. Account created under a collection with an active schedule → `next_due_date` is computed
   immediately from `created_at + interval` (so a fresh account is "due" from day one, not
   floating with no due date).
2. Account created under a collection with no schedule → both columns stay `NULL` forever,
   account behaves exactly like a one-off (current default behaviour, unaffected).
3. A payment reconciles as `exact` or `overpaid` → `last_paid_at = now()`, and
   `next_due_date` recomputed as `last_paid_at + interval`.
4. An `underpaid` payment does **not** advance `next_due_date` — the period isn't considered
   fulfilled yet. It still updates the ledger and balance as normal.

**Interval calculation** uses `dateutil.relativedelta`, not naive day-counting, so calendar
months behave correctly:
- `monthly` → `+ relativedelta(months=1)` (Jan 31 → Feb 28/29 → Mar 28/29, not Mar 31 — avoids
  date drift across uneven months)
- `weekly` → `+ relativedelta(weeks=1)`
- `custom` → `+ timedelta(days=interval_days)`

**Derived status helper** (`get_due_status(account)`), computed on every read, never persisted:
```python
is_overdue:      bool         # next_due_date is not None and now() > next_due_date
days_overdue:    int | None   # (now() - next_due_date).days if overdue else None
days_until_due:  int | None   # (next_due_date - now()).days if not overdue else None
```

This keeps the whole feature to two columns + one small table + one pure helper function —
no background jobs, nothing that can silently fall out of sync.

### `notifications`
```
id            UUID        PK
tenant_id     UUID        FK → tenants.id INDEX
type          VARCHAR     NOT NULL      -- 'payment_received' | 'payment_underpaid' | etc.
title         VARCHAR     NOT NULL
message       TEXT        NOT NULL
data          JSONB       NULL          -- structured payload (account_id, txn_id, amount, etc.)
is_read       BOOLEAN     DEFAULT false
created_at    TIMESTAMPTZ
```

---

## Reconciliation Rules

Every inbound Nomba webhook runs through the reconciliation engine.

| Scenario | Status | Action |
|---|---|---|
| `nomba_account_ref` matches an active virtual account, amount == expected_amount | `exact` | Post credit to ledger |
| `nomba_account_ref` matches, amount > expected_amount | `overpaid` | Post credit, flag difference |
| `nomba_account_ref` matches, amount < expected_amount | `underpaid` | Post credit, flag difference |
| `nomba_account_ref` matches, no expected_amount set | `unmatched` | Post credit, no comparison |
| `nomba_account_ref` does not match any active account | `misdirected` | Record transaction, no ledger entry, flag for manual review |
| `nomba_transaction_ref` already exists in DB | — | Skip (idempotency guard) |

After reconciliation:
- If tenant has a `webhook_url`, forward a `settle.payment.received` event
- Forward failures are logged but never block reconciliation

---

## API Specification

### Base URL
```
https://api.settle.ng/v1
```

### Authentication
Two methods depending on context:

| Method | Header | Used For |
|---|---|---|
| JWT Bearer | `Authorization: Bearer <token>` | Dashboard sessions |
| API Key | `X-Settle-Key: <api_key>` | Developer API access |

Both methods resolve to the same tenant — the API treats them identically after auth.

---

### Auth

#### `POST /v1/auth/register`
Register a new tenant (business).

**Request**
```json
{
  "email": "hello@sunshineestates.ng",
  "password": "strongpassword123",
  "business_name": "Sunshine Estates"
}
```

**Response `201`**
```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "tenant": {
    "id": "uuid",
    "email": "hello@sunshineestates.ng",
    "business_name": "Sunshine Estates"
  },
  "api_key": "sk_live_a1b2c3d4...full_key_shown_once"
}
```

> Only `hashed_api_key` and `api_key_prefix` are persisted. The raw `api_key` above is returned
> **once**, here and in the regenerate response below, and can never be retrieved again — only
> the prefix (e.g. `sk_live_a1b2****`) is shown afterwards for identification in the dashboard.

**Errors**
- `400` — email already registered

---

#### `POST /v1/auth/login`
**Request**
```json
{
  "email": "hello@sunshineestates.ng",
  "password": "strongpassword123"
}
```

**Response `200`**
```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "tenant": {
    "id": "uuid",
    "email": "hello@sunshineestates.ng",
    "business_name": "Sunshine Estates",
    "api_key_prefix": "sk_live_a1b2"
  }
}
```

**Errors**
- `401` — invalid credentials

---

#### `POST /v1/auth/api-key/regenerate`
Regenerates the tenant's API key. The old key is invalidated immediately. The raw key is shown
**once**, in this response only — store it now, it cannot be viewed again afterwards.

**Auth:** JWT only (dashboard action)

**Response `200`**
```json
{
  "api_key": "sk_live_newkey...",
  "api_key_prefix": "sk_live_newk"
}
```

---

#### `POST /v1/auth/logout-all`
Bumps `token_version`, immediately invalidating every JWT previously issued to this tenant.
Used after a password change or suspected compromise.

**Auth:** JWT only

**Response `200`**
```json
{ "message": "All sessions invalidated" }
```

---

#### `PATCH /v1/auth/webhook`
Set or update the tenant's webhook URL for payment event forwarding.

**Request**
```json
{
  "webhook_url": "https://myapp.com/webhooks/settle"
}
```

**Response `200`**
```json
{
  "webhook_url": "https://myapp.com/webhooks/settle"
}
```

---

### Collections

#### `POST /v1/collections`
Create a named collection (e.g. "June Rent 2025"). Recurrence is optional — omit `recurrence`
entirely for a one-off collection. When set, every account provisioned under this collection
automatically inherits the schedule; there is no per-account recurrence config.

**Request**
```json
{
  "name": "June Rent 2025",
  "description": "Monthly rent collection for all units",
  "expected_amount": 45000.00,
  "recurrence": {
    "frequency": "monthly",
    "interval_days": null
  }
}
```

> `interval_days` is only read when `frequency` is `"custom"`. For `weekly`/`monthly` it's
> ignored.

**Response `201`**
```json
{
  "id": "uuid",
  "name": "June Rent 2025",
  "description": "Monthly rent collection for all units",
  "expected_amount": 45000.00,
  "recurrence": { "frequency": "monthly", "interval_days": null },
  "total_accounts": 0,
  "total_paid": 0,
  "created_at": "2025-06-01T00:00:00Z"
}
```

---

#### `GET /v1/collections`
List all collections for the authenticated tenant.

**Query params:** `page`, `limit`, `is_active`

**Response `200`**
```json
{
  "data": [ ...collection objects ],
  "total": 10,
  "page": 1,
  "limit": 20
}
```

---

#### `GET /v1/collections/:id`
Get a single collection with summary stats.

**Response `200`**
```json
{
  "id": "uuid",
  "name": "June Rent 2025",
  "expected_amount": 45000.00,
  "recurrence": { "frequency": "monthly", "interval_days": null },
  "total_accounts": 12,
  "total_paid": 8,
  "total_underpaid": 2,
  "total_unpaid": 2,
  "total_overdue": 1,
  "amount_collected": 380000.00,
  "amount_outstanding": 90000.00,
  "created_at": "2025-06-01T00:00:00Z"
}
```

---

#### `DELETE /v1/collections/:id`
Soft-delete a collection (sets `is_active = false`). Does not delete accounts.

---

### Accounts

#### `POST /v1/accounts`
Provision a virtual account for a single customer.

**Request**
```json
{
  "customer_name": "Emeka Okafor",
  "customer_ref": "unit-12b",
  "customer_email": "emeka@email.com",
  "customer_phone": "08012345678",
  "collection_id": "uuid",
  "expected_amount": 45000.00,
  "description": "Unit 12B — June Rent"
}
```

**Response `201`**
```json
{
  "id": "uuid",
  "customer_name": "Emeka Okafor",
  "customer_ref": "unit-12b",
  "bank_account_number": "9171424534",
  "bank_account_name": "Emeka Okafor/Sunshine Estates",
  "bank_name": "Nombank MFB",
  "expected_amount": 45000.00,
  "payment_page_url": "https://settle.ng/pay/uuid",
  "next_due_date": "2025-07-01T00:00:00Z",
  "created_at": "2025-06-01T00:00:00Z"
}
```

> `next_due_date` is only present if the account's collection has an active recurrence
> schedule. Otherwise it's `null` and the account behaves as a one-off.

**Errors**
- `409` — `customer_ref` already exists for this tenant
- `502` — Nomba account provisioning failed

---

#### `POST /v1/accounts/bulk`
Provision multiple accounts at once. Accepts an array. Processes each independently — partial
success is valid. Returns a result per item.

**Request**
```json
{
  "collection_id": "uuid",
  "accounts": [
    { "customer_name": "Emeka Okafor", "customer_ref": "unit-12b", "expected_amount": 45000 },
    { "customer_name": "Fatima Bello", "customer_ref": "unit-14a", "expected_amount": 45000 }
  ]
}
```

**Response `207`**
```json
{
  "results": [
    { "customer_ref": "unit-12b", "status": "success", "account": { ...AccountOut } },
    { "customer_ref": "unit-14a", "status": "error", "error": "customer_ref already exists" }
  ],
  "total": 2,
  "succeeded": 1,
  "failed": 1
}
```

---

#### `GET /v1/accounts`
List all virtual accounts for the authenticated tenant.

**Query params:** `page`, `limit`, `collection_id`, `status` (paid|unpaid|underpaid|overpaid)

---

#### `GET /v1/accounts/:id`
Get a single virtual account with full detail and current ledger balance.

**Response `200`**
```json
{
  "id": "uuid",
  "customer_name": "Emeka Okafor",
  "customer_ref": "unit-12b",
  "bank_account_number": "9171424534",
  "bank_name": "Nombank MFB",
  "expected_amount": 45000.00,
  "total_paid": 45000.00,
  "balance": 45000.00,
  "payment_status": "exact",
  "payment_page_url": "https://settle.ng/pay/uuid",
  "due_status": {
    "last_paid_at": "2025-06-10T14:32:00Z",
    "next_due_date": "2025-07-10T00:00:00Z",
    "is_overdue": false,
    "days_overdue": null,
    "days_until_due": 10
  },
  "transactions": [ ...TransactionOut ],
  "created_at": "2025-06-01T00:00:00Z"
}
```

> `due_status` is `null` entirely if the account's collection has no recurrence schedule.

---

#### `PATCH /v1/accounts/:id`
Update customer details or expected amount.

**Request** — all fields optional
```json
{
  "customer_email": "new@email.com",
  "expected_amount": 50000.00,
  "description": "Updated description"
}
```

---

#### `DELETE /v1/accounts/:id`
Suspend the virtual account on Nomba and mark as inactive locally.

---

#### `GET /v1/accounts/:id/statement`
Return a paginated ledger statement for a customer.

**Response `200`**
```json
{
  "customer_name": "Emeka Okafor",
  "customer_ref": "unit-12b",
  "bank_account_number": "9171424534",
  "opening_balance": 0,
  "closing_balance": 45000.00,
  "entries": [
    {
      "date": "2025-06-10T14:32:00Z",
      "type": "credit",
      "amount": 45000.00,
      "running_balance": 45000.00,
      "description": "Inbound transfer from Emeka Okafor"
    }
  ]
}
```

---

### Transactions

#### `GET /v1/transactions`
List all transactions for the authenticated tenant.

**Query params:** `page`, `limit`, `status`, `account_id`, `from`, `to`

---

#### `GET /v1/transactions/:id`
Get a single transaction with full detail.

---

#### `GET /v1/transactions/misdirected`
List all misdirected transactions (no matching virtual account found).
Useful for manual review.

---

#### `GET /v1/accounts/:account_id/transactions/:txn_id/receipt`
Generates a PDF receipt on the fly from the transaction, account, and tenant data already in
the database. Nothing new is stored — this is a pure render endpoint, not an invoice system.
Used by the customer-facing payment page so a payer can download proof of payment.

**Response `200`** — `application/pdf` binary stream

**Errors**
- `404` — transaction not found, or doesn't belong to the given account

---

### Notifications

In-app notifications are surfaced two ways: a standard paginated list endpoint for the
dashboard's notification panel, and an SSE stream for real-time delivery while the dashboard
is open. Both read from the same `notifications` table — see
[Notification System](#notification-system) for how entries get created.

#### `GET /v1/notifications`
List notifications for the authenticated tenant, most recent first.

**Query params:** `page`, `limit`, `is_read`

**Response `200`**
```json
{
  "data": [
    {
      "id": "uuid",
      "type": "payment_received",
      "title": "Payment received",
      "message": "Emeka Okafor paid ₦45,000 for Unit 12B",
      "data": { "account_id": "uuid", "transaction_id": "uuid", "amount": 45000.00 },
      "is_read": false,
      "created_at": "2025-06-10T14:32:00Z"
    }
  ],
  "total": 12,
  "unread_count": 4
}
```

---

#### `PATCH /v1/notifications/:id/read`
Mark a single notification as read.

**Response `200`**
```json
{ "id": "uuid", "is_read": true }
```

---

#### `PATCH /v1/notifications/read-all`
Mark every notification for this tenant as read.

**Response `200`**
```json
{ "message": "All notifications marked as read" }
```

---

#### `GET /v1/notifications/stream`
Server-Sent Events stream. Dashboard subscribes on load and receives notifications the moment
they're created — no polling.

**Auth:** JWT only (query param `?token=<jwt>` since `EventSource` cannot set headers)

**Event format**
```
event: notification
data: {"id": "uuid", "type": "payment_received", "title": "...", "message": "...", "data": {...}}

```

Connection stays open; the server sends a `: keep-alive` comment every 30s to prevent
proxy/load-balancer timeouts.

---

### Reports

#### `GET /v1/reports/reconciliation`
Summary reconciliation report across all accounts or filtered by collection.

**Query params:** `collection_id`, `from`, `to`

**Response `200`**
```json
{
  "period": { "from": "2025-06-01", "to": "2025-06-30" },
  "summary": {
    "total_accounts": 50,
    "exact": 35,
    "overpaid": 3,
    "underpaid": 7,
    "unpaid": 5,
    "misdirected": 2
  },
  "amount_expected": 2250000.00,
  "amount_collected": 2010000.00,
  "amount_outstanding": 240000.00
}
```

---

#### `GET /v1/reports/reconciliation/export`
Export reconciliation report as CSV.

**Query params:** `collection_id`, `from`, `to`, `format` (csv only for now)

---

### Webhooks

#### `POST /v1/webhooks/nomba`
Receives inbound transfer events from Nomba. This endpoint is registered with Nomba
and is not called by tenants or developers directly.

**Headers**
```
X-Nomba-Signature: <hmac-sha256 of payload using NOMBA_WEBHOOK_SECRET>
```

**Payload (from Nomba)**
```json
{
  "event": "transfer.credit",
  "data": {
    "transactionRef": "TXN123456",
    "accountRef": "settle-unit-12b-uuid",
    "amount": 45000.00,
    "currency": "NGN",
    "senderAccountNumber": "0123456789",
    "senderAccountName": "EMEKA OKAFOR",
    "senderBankName": "Access Bank",
    "narration": "June rent",
    "transactionDate": "2025-06-10T14:32:00Z"
  }
}
```

**Response `200`** — always, immediately
```json
{ "status": "received" }
```

Reconciliation happens asynchronously in a background task.

---

### Public (No Auth)

#### `GET /v1/pay/:account_id`
Public payment page data. Used by the customer-facing payment page on the frontend.

**Response `200`**
```json
{
  "customer_name": "Emeka Okafor",
  "bank_account_number": "9171424534",
  "bank_account_name": "Emeka Okafor/Sunshine Estates",
  "bank_name": "Nombank MFB",
  "expected_amount": 45000.00,
  "description": "Unit 12B — June Rent",
  "payment_status": "unpaid",
  "next_due_date": "2025-07-10T00:00:00Z",
  "business_name": "Sunshine Estates"
}
```

> `next_due_date` is `null` if the account isn't on a recurring collection.

**Errors**
- `404` — account not found or inactive

---

## Notification System

One entry point, zero branching at the call site. Anywhere in the codebase that needs to tell
a tenant something happened does exactly this:

```python
background_tasks.add_task(
    notification_manager.notify,
    context=PaymentReceivedContext(tenant_id=..., account_id=..., amount=..., status=...),
)
```

The `NotificationManager` is a factory over channel handlers:

```python
class NotificationChannel(Protocol):
    async def send(self, tenant: Tenant, context: NotificationContext) -> None: ...

CHANNELS: dict[str, NotificationChannel] = {
    "in_app": InAppChannel(),     # writes to `notifications` table, pushes via SSE
    "email": EmailChannel(),      # Resend API
    "webhook": WebhookChannel(),  # reuses the same forwarder as reconciliation
}
```

`notify()` doesn't ask "should I send email?" with an if-statement — it asks each configured
channel for this tenant to handle the context, and every channel fails independently:

```python
async def notify(self, context: NotificationContext) -> None:
    for channel in self._channels_for(context.tenant):
        try:
            await channel.send(context.tenant, context)
        except Exception:
            logger.exception(f"{channel} failed for tenant {context.tenant.id}")
            # one channel failing never blocks another
```

`_channels_for(tenant)` is the only place that knows which channels are "on" for a given
tenant (in-app is always on; email is on if the tenant has an email — which they always do;
webhook is on only if `tenant.webhook_url` is set). Adding SMS later is one new class added to
`CHANNELS` and one line in `_channels_for` — nothing else in the codebase changes.

**v1 channels:** `in_app` (SSE-backed) and `webhook` are fully wired. `email` is wired through
Resend. `sms` is stubbed behind the same `NotificationChannel` protocol but not implemented —
swapping it in later is a single new file.

---

## Nomba Integration

### Authentication
Nomba uses OAuth2 client credentials. A token must be fetched before every request
(or cached with its TTL).

```
POST https://api.nomba.com/v1/auth/token/grant
{
  "grant_type": "client_credentials",
  "client_id": "<NOMBA_CLIENT_ID>",
  "client_secret": "<NOMBA_CLIENT_SECRET>"
}
```

Cache the token in Redis with TTL = `expires_in - 60` seconds.

### Virtual Account Provisioning
```
POST https://api.nomba.com/v1/accounts/virtual
Headers:
  Authorization: Bearer <nomba_token>
  accountId: <NOMBA_ACCOUNT_ID>

Body:
{
  "accountRef": "<nomba_account_ref>",   -- our internal unique ref
  "accountName": "<customer_name>",
  "currency": "NGN",
  "expectedAmount": <expected_amount>    -- optional
}
```

`nomba_account_ref` format: `settle-<tenant_id_short>-<customer_ref>-<uuid_short>`
This ensures uniqueness across tenants and is how we match inbound webhooks back to
the right customer.

### Account Suspension
```
PUT https://api.nomba.com/v1/accounts/suspend/<nomba_account_id>
```

---

## Webhook System

### Inbound (Nomba → Settle)
1. Nomba POSTs to `POST /v1/webhooks/nomba`
2. Settle validates HMAC-SHA256 signature
3. Settle responds `200` immediately
4. Background task runs reconciliation engine
5. Ledger updated, transaction recorded

### Outbound (Settle → Tenant)
After successful reconciliation, if tenant has a `webhook_url`:

```json
{
  "event": "settle.payment.received",
  "data": {
    "transaction_id": "uuid",
    "virtual_account_id": "uuid",
    "customer_ref": "unit-12b",
    "customer_name": "Emeka Okafor",
    "amount": 45000.00,
    "status": "exact",
    "paid_at": "2025-06-10T14:32:00Z"
  }
}
```

- Timeout: 10 seconds
- No retries in v1 (planned for v2)
- Failures logged, never block reconciliation

---

## Edge Cases

| Case | Handling |
|---|---|
| Duplicate webhook from Nomba | Idempotency check on `nomba_transaction_ref` — skip if exists |
| Payment to unknown account ref | Recorded as `misdirected`, flagged for manual review |
| Overpayment | Recorded as `overpaid`, difference stored, tenant notified via webhook |
| Underpayment | Recorded as `underpaid`, difference stored, tenant notified |
| Bulk provisioning partial failure | `207` response, succeeded and failed items reported separately |
| Nomba token expired | Redis cache miss triggers re-auth before retrying |
| Tenant webhook URL is down | Forward attempt logged, reconciliation unaffected |
| Account suspended mid-payment | Payment recorded as misdirected if account marked inactive before webhook arrives |
| Underpayment on a recurring account | Ledger and balance still update; `next_due_date` does **not** advance — period stays open until a qualifying payment lands |
| Monthly recurrence starting Jan 31 / Mar 31 | `relativedelta` rolls correctly to the last valid day of the next month (e.g. Feb 28/29) instead of overflowing into March |
| Collection recurrence changed after accounts already exist | Existing accounts keep their current `next_due_date`; new interval applies from their *next* computed due date onward |

---

## Out of Scope (v1)

- Payouts / withdrawals (Nomba Transfers API) — planned v2
- Webhook retries with exponential backoff — planned v2
- Multi-user tenants (team members) — planned v2
- Card checkout / payment links — planned v2
- SMS notifications — explicitly skipped, Nigerian SMS providers need business verification
- KYC tier change handling — planned v2
- Per-account recurrence overrides — recurrence is collection-level only in v1
- Mobile app — not applicable

---

## Environment Variables

```env
# App
APP_ENV=development
SECRET_KEY=

# Database
DB_HOST=
DB_PORT=5432
DB_USER=
DB_PASSWORD=
DB_NAME=

# Redis
REDIS_HOST=
REDIS_PORT=6379
REDIS_PASSWORD=

# JWT
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# Nomba
NOMBA_CLIENT_ID=
NOMBA_CLIENT_SECRET=
NOMBA_ACCOUNT_ID=
NOMBA_BASE_URL=https://api.nomba.com/v1
NOMBA_WEBHOOK_SECRET=

# Email (Resend)
RESEND_API_KEY=
EMAIL_FROM=notifications@settle.ng

# CORS
ALLOWED_ORIGINS=http://localhost:3000
```
