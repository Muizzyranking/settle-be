# Settle

> Payment collection infrastructure for Nigerian SMEs and the developers who build for them.

Settle is a full-stack payment infrastructure platform built on top of Nomba's Virtual Account and Transfers APIs. It solves a specific, recurring problem in the Nigerian payments landscape: businesses that collect money from multiple customers — landlords, schools, cooperatives, freelancers — have no reliable way to automatically know who paid, how much, and whether the payment was complete. Everything is manual. Settle automates the entire flow.

---

## The Problem

When a landlord collects rent from 50 tenants, all 50 transfers land in the same bank account. There is no automatic way to match a transfer to a specific tenant. The landlord manually checks their phone, cross-references names against a list, calls tenants, or reconciles a bank statement at the end of the month. At 10 tenants this is annoying. At 50 it is unmanageable. At 200 it breaks entirely.

Schools face the same problem with student fees. Cooperatives face it with monthly contributions. Freelancers face it when managing multiple client invoices. The pattern is identical: one shared account, many payers, no automatic attribution.

On the developer side, every engineering team building a collection product for these businesses rebuilds the same infrastructure from scratch — virtual account provisioning, webhook handling, reconciliation logic, ledger management, notification dispatch.

Settle solves both problems in one platform.

---

## The Solution

Settle gives each customer their own dedicated Nomba virtual bank account number. When a tenant pays rent, they transfer to their specific account number — not a shared one. When the money arrives, Settle automatically knows it is from that tenant, records the payment against their balance, computes the reconciliation status, and notifies the business in real time.

This works for any volume. A landlord with 200 tenants provisions 200 account numbers. Each transfer is automatically attributed. The landlord sees, in real time, who has paid, who has not, who paid short, and who overpaid. No manual reconciliation.

The same engine is exposed as a clean REST API, so developers building rent collection apps, school fees platforms, or cooperative management systems can integrate Settle instead of building the infrastructure themselves.

---

## Two Audiences, One Platform

**SMEs (non-technical users)** interact with the dashboard — a web application that lets them create collections, add customers, generate account numbers in bulk, monitor payment status, manage recurring billing, and withdraw their collected funds. No API knowledge required.

**Developers** use the REST API with API key authentication. They get the same reconciliation engine, webhook forwarding with signed payloads, per-customer ledger access, and comprehensive documentation. They build their products on top of Settle rather than on top of raw Nomba primitives.

The dashboard itself is a consumer of the developer API. This is intentional: it proves the API works in production, not just in documentation.

---

## Core Features

### Virtual Account Provisioning
Every customer gets a dedicated Nomba bank account number. Accounts are provisioned via Nomba's sub-account API so funds collect in the business's designated sub-account rather than a shared pool. Account numbers are permanent by default, or can be expired when a customer relationship ends.

### Automatic Reconciliation
Every inbound transfer triggers a Nomba webhook. Settle processes it asynchronously, matches it to the right customer account using the `accountRef`, and determines the reconciliation status:

- **Exact** — the customer paid precisely what was expected
- **Underpaid** — the payment was less than expected (the period stays open)
- **Overpaid** — the payment exceeded the expected amount (tracked for potential refund)
- **Unmatched** — no expected amount was set, payment received and recorded
- **Misdirected** — the payment arrived but could not be matched to any active account

The reconciliation engine is idempotent. If Nomba sends the same webhook twice, the second one is a no-op. Nothing is double-counted.

### Ledger Per Customer
Every matched payment posts a credit entry to an append-only ledger. The ledger tracks the running balance per customer. This means the balance is never computed on the fly — it is always the `running_balance` from the most recent ledger entry. Statements can be generated per customer showing every credit and their running balance at each point.

### Recurring Billing
Collections can carry a recurring schedule — monthly, weekly, or a custom interval in days. Every account provisioned under a recurring collection inherits the schedule automatically. When a qualifying payment lands, the system advances `last_paid_at` and recomputes `next_due_date` using calendar-correct date math. Monthly billing from January 31 correctly produces February 28 or 29, not March 2 — this is handled with `dateutil.relativedelta` rather than naive day-counting.

Underpayments do not advance the due date. A billing period is only considered fulfilled when the payment meets or exceeds the expected amount.

### Real-Time Updates
Payment confirmation is delivered instantly through two separate Server-Sent Event streams backed by Redis pub/sub:

The **tenant notification stream** delivers payment events to the business dashboard the moment reconciliation completes. The notification bell increments, a toast appears, and the relevant collection or account updates without a page reload.

The **customer payment page stream** updates the customer's browser the moment their transfer is reconciled. A customer who opens the payment page and transfers money from their banking app sees "Payment confirmed" appear on the page when they return — no refresh, no delay.

### Withdrawals and Refunds
Businesses can withdraw collected funds to their registered bank account using Nomba's Transfers API. Destination accounts are verified via Nomba's bank lookup endpoint before being saved, ensuring the account name is confirmed before any transfer is made.

Overpaid accounts can be refunded. The refund endpoint accepts a destination account number and bank, verifies the account name via Nomba lookup, and transfers the exact overpaid amount back to the customer. The refund amount is capped at the overpaid difference and cannot exceed it.

### Developer API
The REST API exposes every platform capability — collection management, account provisioning, reconciliation data, ledger access, financial operations — behind API key authentication. API keys are generated on explicit request, stored as SHA-256 hashes (the raw key is shown once and never again), and can be used as a drop-in alternative to JWT authentication via the `X-Settle-Key` header.

Developers can register a webhook URL to receive signed payment events. Every outbound webhook payload is signed with HMAC-SHA256 using a per-tenant secret the developer sets themselves. A test webhook endpoint lets developers verify their endpoint is receiving and validating signatures correctly before going live.

### Authentication
Email and password registration with mandatory email verification — unverified accounts are blocked at every protected endpoint. Google OAuth with a secure token exchange pattern: the browser is redirected to Google, Google calls the backend callback, the backend issues a short-lived one-time code and redirects to the frontend, and the frontend exchanges the code for real tokens server-side. Real tokens never appear in the URL or browser network tab.

Access tokens (24 hours) and refresh tokens (30 days) are stored in httpOnly cookies managed by the Next.js server layer. The browser never has direct access to authentication tokens. Token versioning allows instant invalidation of all sessions when a password changes or a security event is detected.

---

## Technical Stack

### Backend
**FastAPI** (Python 3.12) serves as the API framework. Its async-first design and automatic OpenAPI generation suit both the high-throughput webhook processing and the developer-facing API documentation requirements.

**PostgreSQL 16** is the primary database, accessed asynchronously via SQLAlchemy 2.0 with the asyncpg driver. The schema uses proper relational modelling — collections contain accounts, accounts have transactions, transactions post to ledger entries — with appropriate constraints and indexes for the query patterns the application actually runs.

**Redis 7** serves two distinct purposes. First, it caches Nomba's OAuth access tokens with a 55-minute TTL, so the application never requests a new token per API call. A Redis lock prevents multiple workers from simultaneously requesting tokens when the cache expires under concurrent load (the thundering herd problem). Second, it serves as the pub/sub backbone for Server-Sent Events — when reconciliation completes, it publishes to Redis channels that feed both the tenant notification stream and the customer payment page stream.

**uv** manages Python dependencies. The lockfile ensures reproducible installs across development and production.

**Railway** hosts the backend with PostgreSQL and Redis as managed add-ons. The Dockerfile uses the official uv Docker image for fast, reproducible builds and runs the application as a non-root user.

### Frontend
**Next.js** (App Router) serves both the marketing site (`settle.ng`) and the dashboard application (`app.settle.ng`) from a single deployment on Vercel. A `proxy.ts` file handles subdomain routing — unauthenticated users attempting to access the dashboard are redirected to login, authenticated users on the marketing site are redirected to the dashboard.

All API calls from browser components are routed through Next.js API routes that attach authentication tokens from server-side httpOnly cookies. Tokens are never accessible to browser JavaScript. The SSE notification stream is also proxied server-side to prevent the JWT from appearing in the network tab as a URL query parameter.

### Nomba Integration
The application integrates three Nomba API surfaces:

**Virtual Account API** — accounts are provisioned against the team's sub-account ID (`NOMBA_SUB_ACCOUNT_ID`) so collected funds aggregate in the correct sub-account. Account expiry uses `DELETE /v1/accounts/virtual/{accountRef}` rather than the suspend endpoint, which resolved a 403 error encountered during development.

**Transfers API (v2)** — used for both tenant withdrawals and customer refunds. Every transfer is preceded by a bank account name lookup to verify the destination before committing.

**Webhook processing** — Nomba sends `payment_success` events to `POST /v1/webhooks/nomba`. The signature is verified using the `nomba-signature` and `nomba-timestamp` headers. Processing is handed off to a background task immediately so the endpoint returns 200 before reconciliation completes.

---

## Architecture Decisions Worth Explaining

### Why two SSE channels
The tenant notification stream is authenticated — it delivers business-level events (who paid, how much, which collection) and must be scoped to a specific tenant. The customer payment page stream is public — it delivers only the status of one specific payment and contains no business-sensitive information. Combining them would either expose business data to customers or require unnecessary authentication on the payment page. Keeping them separate keeps the security model clean.

### Why the notification manager is a factory
The reconciliation engine needs to notify several channels when a payment lands — in-app notification, email, and webhook. If the code checked "does this tenant have a webhook? if yes, send. Does Resend work? if yes, send email." at the call site, adding a new channel (WhatsApp, SMS) would require touching the reconciliation code. Instead, the reconciliation engine calls `notification_manager.notify(context)` and the manager handles dispatch internally. Each channel fails independently and logs its own errors. Adding a new channel means writing one new channel class — nothing else changes.

### Why underpayments do not advance the due date
In a recurring billing model, the purpose of the due date is to track whether the obligation for a given period has been fulfilled. An underpayment means the obligation has not been fulfilled — the period is still open. Advancing the due date on an underpayment would mean the business could not tell that a customer still owes money for the current cycle. The remaining balance stays visible in the ledger and the payment status stays `underpaid` until a qualifying payment lands.

### Why API keys are SHA-256 and passwords are Argon2
Password hashing uses Argon2 (via `pwdlib`) because slow-by-design hashing is the security property that matters — an attacker who steals the hash database should not be able to brute-force passwords quickly. API keys are different: they are long random strings (48 hex bytes of entropy), so brute force is not a realistic attack vector. What matters for API keys is fast, deterministic lookup on every authenticated request. SHA-256 provides that without the computational overhead of Argon2.

### Why token versioning
Refresh token rotation means a stolen refresh token will be invalidated after one use, since each use revokes the old token and issues a new one. But what about access tokens, which are valid for 24 hours? If a user's account is compromised or they log out of all devices, the access token could still be used until it expires. Token versioning solves this: every JWT includes the tenant's current `token_version`, and the auth dependency rejects tokens where the version in the JWT does not match the version in the database. Incrementing the version in the database instantly invalidates every previously issued access token.

---

## Database Schema

```
tenants                    — business accounts, auth credentials, settings
collections                — named payment groups
recurring_schedules        — frequency config, one per collection
virtual_accounts           — one per customer, tracks due dates and payment state
transactions               — every inbound payment, reconciliation status
ledger_entries             — append-only credit log with running balance
notifications              — in-app notification store
tenant_bank_accounts       — saved withdrawal destinations (max 3 per tenant)
refresh_tokens             — rotating long-lived session tokens
email_verification_tokens  — single-use email verification
password_reset_tokens      — single-use password reset
google_oauth_codes         — single-use 5-minute Google OAuth exchange codes
```

---

## API Surface

46 endpoints across 11 feature areas, all documented in `FE_INTEGRATION.md` and `SPEC.md`.

| Area | Endpoints |
|------|-----------|
| Auth | 12 |
| Collections | 4 |
| Accounts | 6 |
| Transactions | 4 |
| Reports | 3 |
| Dashboard | 1 |
| Finance | 2 |
| Notifications | 4 |
| Settings | 7 |
| Public (no auth) | 2 |
| Webhooks | 1 |

---

## Running Locally

**Prerequisites:** Python 3.12, uv, Docker

```bash
# Clone and install
git clone https://github.com/your-org/settle-be
cd settle-be
uv sync

# Configure environment
cp .env.example .env
# Fill in Nomba credentials, DB connection, Redis connection, etc.

# Start dependent services
docker compose up postgres redis -d

# Run the API
uv run uvicorn app.main:app --reload --port 8000
```

Set `ENABLE_DOCS=true` in `.env` to access the Swagger UI at
`http://localhost:8000/docs`.

Register your public URL (or ngrok tunnel) as the Nomba webhook endpoint:
```
https://your-url/v1/webhooks/nomba
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | Yes | JWT signing key — generate with `openssl rand -hex 32` |
| `DB_HOST` | Yes | PostgreSQL host |
| `DB_PORT` | Yes | PostgreSQL port (default 5432) |
| `DB_USER` | Yes | PostgreSQL user |
| `DB_PASSWORD` | Yes | PostgreSQL password |
| `DB_NAME` | Yes | PostgreSQL database name |
| `REDIS_HOST` | Yes | Redis host |
| `REDIS_PORT` | Yes | Redis port (default 6379) |
| `NOMBA_CLIENT_ID` | Yes | Nomba API client ID |
| `NOMBA_CLIENT_SECRET` | Yes | Nomba API client secret |
| `NOMBA_ACCOUNT_ID` | Yes | Nomba parent account ID |
| `NOMBA_SUB_ACCOUNT_ID` | Yes | Nomba sub-account ID — virtual accounts provision here |
| `NOMBA_WEBHOOK_SECRET` | Yes | Secret for verifying inbound Nomba webhook signatures |
| `GOOGLE_CLIENT_ID` | No | Google OAuth client ID (Google auth disabled if absent) |
| `GOOGLE_CLIENT_SECRET` | No | Google OAuth client secret |
| `GOOGLE_REDIRECT_URI` | No | Google OAuth callback URL |
| `FRONTEND_URL` | No | Frontend base URL for email links (default: https://app.settle.ng) |
| `RESEND_API_KEY` | No | Resend email API key (email disabled if absent) |
| `EMAIL_FROM` | No | From address for outbound emails |
| `ENABLE_DOCS` | No | Set to `true` to enable Swagger UI (disabled by default) |

---

## Project Structure

```
app/
├── main.py                              FastAPI application, router registration
├── core/
│   ├── config.py                        Environment-driven settings
│   └── security.py                      Password hashing, JWT, API key generation
├── db/
│   ├── database.py                      Async SQLAlchemy engine and session
│   └── redis.py                         Redis client lifecycle
├── models/                              SQLAlchemy ORM models
│   ├── tenant.py
│   ├── collection.py                    Collection + RecurringSchedule
│   ├── account.py                       VirtualAccount
│   ├── transaction.py
│   ├── ledger.py
│   ├── notification.py
│   ├── bank_account.py
│   ├── refresh_token.py
│   └── auth_tokens.py                   Email verification, password reset, Google OAuth codes
├── schemas/                             Pydantic request/response models
├── api/
│   ├── deps.py                          Shared auth dependency (JWT + API key)
│   └── routes/
│       ├── auth.py
│       ├── collections.py
│       ├── accounts.py
│       ├── transactions.py
│       ├── reports.py
│       ├── dashboard.py
│       ├── finance.py
│       ├── notifications.py
│       ├── settings.py
│       ├── developers.py
│       ├── pay.py                       Public payment page endpoints
│       └── webhooks.py                  Nomba inbound webhook receiver
└── services/
    ├── nomba_client.py                  Nomba OAuth client with Redis token cache
    ├── nomba_accounts.py                Nomba API wrapper (accounts, transfers, lookups)
    ├── account_provisioning.py          Virtual account create and expire
    ├── account_detail.py                Balance and payment status computation
    ├── collection_service.py            Collection create and stats aggregation
    ├── reconciliation.py                Core reconciliation engine
    ├── recurrence.py                    Calendar-correct due date math
    ├── receipt.py                       PDF receipt generation (ReportLab)
    ├── email_service.py                 Transactional email via Resend
    └── notifications/
        ├── context.py                   Typed notification context dataclasses
        ├── manager.py                   Channel factory and dispatch
        └── channels/
            ├── in_app.py                DB write + Redis pub/sub for SSE
            ├── webhook.py               HMAC-signed outbound webhook forward
            └── email.py                 Email channel via Resend
```

---

## Documentation

| File | Contents |
|------|----------|
| `SPEC.md` | Full API specification — every endpoint, request/response shape, database schema, reconciliation rules, edge cases |
| `FE_INTEGRATION.md` | Frontend integration guide — auth flows, token strategy, SSE implementation, Next.js proxy pattern, webhook verification |
| `AI_AGENT_CONTEXT.md` | Context document for AI-assisted frontend development — full flow explanation, UX priorities, judging criteria |
| `PAGES.md` | Page-by-page element specification for the frontend — every page, its purpose, and every element it should contain |
| `SUBMISSION.md` | Hackathon submission documentation |

---

## What This Project Demonstrates

**Systems thinking.** The architecture separates concerns cleanly — routes are thin, services own logic, the notification system is a factory, the Nomba client is the only code that knows about Nomba's auth. Each module does one thing. None of them know about each other's internals.

**Production-grade engineering under time pressure.** Idempotent webhook processing, Redis-locked token refresh, rotating refresh tokens, token versioning, append-only ledger, soft deletes, per-tenant secrets — these are not features added for show. They are what the system needs to be reliable when real money is involved.

**API design.** The dual-surface architecture (SME dashboard + developer API) required thinking carefully about what the API contract should be. The dashboard consuming the same API that external developers use is not a coincidence — it is a constraint that forced the API to be well-designed enough to build a real product on top of.

**Real-time systems.** Two SSE channels with different security and scoping requirements, backed by Redis pub/sub, with server-side proxying on the frontend to keep tokens off the network. Understanding why each design decision was made, not just how to implement it.

**Security by default.** Tokens in httpOnly cookies, Google OAuth exchange codes, SHA-256 for fast lookup vs Argon2 for slow password hashing, token versioning, HMAC-signed webhooks, API keys shown once and never stored in plaintext. Security decisions made for the right reasons, not as an afterthought.

Built solo in under one week.
