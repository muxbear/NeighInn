# Neighbor's Inn (NeighInn)

**English** | [简体中文](README.zh-CN.md)

Neighbor-to-neighbor idle-item sharing and trading for residential communities — free gifting, item barter, and escrow-protected monetary trades, backed by AI-assisted quality inspection and a full community operations console.

![Platforms](https://img.shields.io/badge/platform-Android%20%7C%20iOS%20%7C%20HarmonyOS%20%7C%20WeChat%20MP%20%7C%20H5-FF7A3D)
![Mobile](https://img.shields.io/badge/mobile-uni--app%20x%20%28Vapor%29-6BB88A)
![Admin](https://img.shields.io/badge/admin-Vue%203%20%2B%20Vite-6F59D4)
![Backend](https://img.shields.io/badge/backend-FastAPI%20%2B%20PostgreSQL-009688)
![Tests](https://img.shields.io/badge/tests-127%20backend%20%C2%B7%2041%20mobile-brightgreen)
![Status](https://img.shields.io/badge/status-active%20development-orange)
![License](https://img.shields.io/badge/license-not%20specified-lightgrey)

## Table of contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Repository layout](#repository-layout)
- [Getting started](#getting-started)
- [Ports and accounts](#ports-and-accounts)
- [Configuration](#configuration)
- [API conventions](#api-conventions)
- [Quality gates](#quality-gates)
- [Documentation](#documentation)
- [Current status and roadmap](#current-status-and-roadmap)
- [Contributing](#contributing)
- [Security](#security)
- [License](#license)

## Overview

NeighInn (邻里小栈) is a community-based O2O marketplace where verified owners in the same or nearby residential communities (3 km by default) share and trade idle items. Listings are discovered online and inspected/handed over offline. Every item passes an AI quality check, with low-confidence or flagged listings routed to human review before going live.

The platform supports three complete transaction modes:

| Mode | Flow |
| --- | --- |
| **Free gifting** | Apply → counterparty confirms → appointment → handover |
| **Item barter** | Apply with an expected swap item → counterparty confirms → appointment → exchange |
| **Monetary escrow** | Pay into platform escrow → offline inspection → buyer confirms satisfaction → funds released to seller |

A single FastAPI backend serves both the mobile app and the admin console, sharing one domain model, one database, and one set of state machines. This avoids double writes and keeps both ends consistent through domain events and cache invalidation.

## Features

### Mobile app (40 screens, 42 components)

Built with uni-app x Vapor + Vue 3 Composition API + TypeScript + Pinia. Targets Android 6.0+, iOS 15+, HarmonyOS 6.0+ (API 20+), WeChat Mini Program (base library 3.7.1+), and H5 (used for local development at port 5191).

- **Onboarding and trust**
  - Phone + SMS verification with separate `login` and `register` intents.
  - Newcomer onboarding: nickname, avatar, intended community, agreement-version records.
  - Real-name verification and home-ownership proof with review status, supplement, and rejection flows.
  - Certification center and certification result screens.
- **Discovery and community**
  - Home dashboard: dedicated trade zones, broadcast-board carousel, community found items, neighbor help, community life feed.
  - Nearby communities and items within a configurable radius (3 km default, Haversine distance).
  - Keyword search and filters, four dedicated zones (gift / barter / sale / help).
  - Item detail with media carousel, seller trust panel, comments, favorites, private chat, and three trade entries.
- **Publishing and AI quality inspection**
  - Three-step item publish flow with drafts, up to 12 photos, video/certificate upload.
  - AI quality report covering image quality, image–text consistency, compliance, and condition suggestion.
  - AI audit progress/report screens, fast-track pass for high confidence, manual review otherwise.
  - Edit and resubmit with a fresh AI audit; item management and listing lifecycle.
- **Transactions**
  - Complete free-gift, barter, and monetary escrow flows.
  - Cashier, appointment/reschedule, inspection with dual confirmation, auto-release after 72 hours.
  - Reviews, disputes, wallet with balance/escrow/withdrawable amounts.
- **Social and notifications**
  - Friends and friend requests (real-name gate, request caps).
  - One-to-one IM with read receipts, content-safety checks, and idempotent message sending.
  - Notification center with categories, unread counts, and per-category settings.
  - Report flow for items, content, and users.
- **Profile and safety**
  - Profile editing, built-in avatar library, favorites and browsing footprints, credit center.
  - Community management, help center, settings, and a custom five-tab bottom bar with a central publish action.
  - Global request layer with Bearer token, refresh-token renewal, idempotency keys, error mapping, and retries; WebSocket client with heartbeat and exponential backoff.

### Admin console (Vue 3, 23 sidebar modules)

- **Dashboard**
  - Community switcher, headline metrics, seven-day activity trend, resident structure, recent activity.
  - Live todo queue (certification, item review, help, reports, repairs) with badge counters.
- **Community operations**
  - Community broadcast: create/edit, schedule, publish, take offline, review states.
  - Community items: search, review, recommend, take offline, batch operations, trade-type filters.
  - Neighbor help: help requests and neighbor services, review, matching, completion, closure.
  - Community life: review, publish/offline (comment governance is available through the backend API).
- **Community management**
  - Administrative region tree and community CRUD; coordinates required, contact details encrypted, disable makes the community invisible to the app.
  - Resident directory and resident certification review queue (approve, reject with a minimum reason length, request supplements; community correction is supported by the backend API).
- **Finance and governance**
  - Fund dashboard, ledger transactions, withdrawal management with dual review, reconciliation, read-only order snapshots.
  - Dispute mediation with real escrow freeze and disposition types (continue, refund, force release, partial refund, credit, account freeze); fund dispositions enter dual review.
  - Report workbench: dismiss, take content offline, delete comments, mute, ban.
- **Reach**
  - Announcements: publish triggers in-app notifications and read statistics.
  - Notification tasks: audience estimate, send, and delivery details.
- **System**
  - Users: search and enable/disable in the console; the backend API additionally supports 360° profiles and penalties (warning / mute / publish limit / trade limit / ban), plus restore.
  - RBAC roles and permission tree, page resource management, runtime parameters (admin-account management is available through the backend API).
  - Parameter changes are published immediately to the mobile AppConfig; audit logs and CSV report export jobs are available (the export page is still a placeholder).
- **Extensions**
  - Repair orders: dispatch and completion.
  - Feedback: reply and close.
  - Report export UI and four community extension modules are still placeholders.
- **Access control**
  - HttpOnly cookie session, CSRF double-submit, and login lockout; TOTP 2FA with one-time recovery codes is implemented in the backend (enrollment UI pending).
  - Permission-gated routes and navigation, data-scope filtering, and append-only audit logging.

### Unified backend

- **Domain model**: 70 tables across bounded contexts, managed by 9 Alembic migrations.
- **State machines**: 8 machines (item, order, certification, withdrawal, fund adjustment, dispute, content, help) with a single transition entry point in `web/backend/src/domain/state.py`.
- **Contracts**: 104 consumer-facing (C-end) endpoints under `/api/v1` and 173 admin endpoints under `/api/v1/admin`.

| Contract | Domains |
| --- | --- |
| C-end `/api/v1` | auth · catalog · home · items · engagement · life · services · broadcasts · orders · payments · wallet · notifications · social · communities · users · uploads · reports · WebSocket |
| Admin `/api/v1/admin` | auth · accounts · dashboard · communities · residents · operations · content ops · communication · governance · finance · system · users · files · exports |
- **Authentication**: JWT access/refresh for the app; cookie session + CSRF + optional TOTP for the console.
- **Money**: all amounts are integer cents; balances are derived only from double-entry `ledger_entries`; escrow, release, refund, withdrawal, and dispute dispositions are fully ledgered.
- **Consistency**: all writes accept `X-Idempotency-Key`; order creation enforces one active order per item; state changes are rejected if illegal.
- **Operations**: in-process outbox relay and timeout scheduler (payment timeout, confirmation timeout, auto-release, listing expiry); RabbitMQ optional.
- **Files**: MinIO public/private/system buckets with short-lived signed URLs; private identity materials never exposed directly.
- **Observability**: structured logs with `traceId`, sensitive-field masking, access logs, and slow-request warnings.
- **Realtime**: WebSocket `/api/v1/ws` for IM messages, order events, audit events, and notifications.
- **Quality**: 127 backend tests covering authentication/registration, certification, items, orders and funds, content/social, admin flows, WebSocket, timeouts, outbox, and 2FA.

> External integrations for payment, SMS, push, real-name verification, and AI quality inspection are currently mock adapters. The interfaces are in place; production adapters are on the roadmap.

## Architecture

```
┌────────────────────────────┐          ┌─────────────────────────────┐
│  Mobile app · uni-app x    │          │  Admin console · Vue 3      │
│  Android / iOS / HarmonyOS │          │  Vite · port 5192           │
│  WeChat MP · H5 (5191)     │          └──────────────┬──────────────┘
└─────────────┬──────────────┘                         │ /api proxy
              │ /api/v1 (JWT Bearer)                   │ /api/v1/admin
              │                                        │ (Cookie + CSRF)
              ▼                                        ▼
       ┌──────────────────────────────────────────────────────┐
       │        Unified FastAPI backend · port 5193           │
       │  Consumer API · Admin API · WebSocket /api/v1/ws     │
       │  state machines · RBAC · audit · idempotency         │
       └───────┬───────────────┬───────────────┬──────────────┘
               ▼               ▼               ▼
          PostgreSQL         Redis           MinIO
        (shared domain   (sessions/SMS    (public/private
             data)          codes/cache)      buckets)
               │
               ▼
        Outbox → RabbitMQ (optional) → in-process workers
        (timeout tasks · outbox relay)
```

## Tech stack

| Layer | Technology |
| --- | --- |
| Mobile | uni-app x Vapor, Vue 3 Composition API, TypeScript, Pinia 2, SCSS/ucss, Vitest |
| Admin frontend | Vue 3.5, TypeScript, Pinia, Vue Router 4, Vite 6, SCSS, Lucide, Axios |
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2.0 async, Pydantic 2, Alembic, PyJWT, WebSocket |
| Data and infrastructure | PostgreSQL 16, Redis 7, MinIO, RabbitMQ (optional), SQLite for tests |
| Build and quality | HBuilderX 5.34, npm, Vitest, uv, ruff, pytest, Docker Compose |

## Repository layout

```
NeighInn/
├── mobile/                     # uni-app x (Vapor) mobile app
│   ├── pages/                  # 40 screens (20 main + 20 subpackage)
│   ├── components/             # 42 ni-* UI and business components
│   ├── composables/            # useAuth / useIM / usePay / useUpload / useAudit ...
│   ├── services/               # business services, including ws.service.ts
│   ├── api/                    # request.ts + mock.ts + *.api.ts
│   ├── stores/                 # 9 Pinia stores
│   ├── models/                 # typed API models
│   ├── config/                 # environments, constants, mock fixtures
│   ├── styles/                 # tokens/reset/typography; uni.scss is canonical
│   ├── tests/                  # Vitest logic tests
│   └── docs/                   # mobile detailed design
├── web/
│   ├── backend/                # FastAPI unified server
│   │   ├── src/api/c_end/      # /api/v1 (JWT Bearer)
│   │   ├── src/api/admin/      # /api/v1/admin (Cookie + CSRF)
│   │   ├── src/db/models/      # 70 tables by bounded context
│   │   ├── src/domain/         # business enums + 8 state machines
│   │   ├── src/services/       # auth / item / AI audit / order / payment / IM
│   │   ├── alembic/            # 9 migrations
│   │   ├── tests/              # 127 tests
│   │   └── scripts/            # smoke_e2e.py
│   ├── frontend/               # Vue 3 admin console
│   └── docs/                   # admin console design specification
├── docs/                       # SRS, UI/UX specification, evaluation report
├── CLAUDE.md                   # engineering guide for this repository
└── README.zh-CN.md             # Chinese README
```

> The repository root directory name ends with an invisible **U+200C (ZERO WIDTH NON-JOINER)** character. When using the path in a terminal, copy it or use a wildcard such as `NeighInn*`; do not retype it.

## Getting started

### Prerequisites

| Tool | Version | Purpose |
| --- | --- | --- |
| Node.js + npm | Node 18+ (20+ recommended) | Admin console, mobile static checks and tests |
| Python + uv | Python 3.11+, latest uv | Unified backend |
| HBuilderX | 5.34 | Compile and run the uni-app x app |
| Docker + Compose | Optional | PostgreSQL / Redis / MinIO / RabbitMQ |
| PostgreSQL | 16 (optional if using Docker) | Production-style database |
| WeChat DevTools | Optional | WeChat Mini Program preview |

### 1. Start the unified backend

```bash
cd web/backend
cp .env.example .env      # review secrets and connection strings
uv sync --dev

# Optional: start PostgreSQL / Redis / MinIO / RabbitMQ
docker compose up -d

# Apply schema migrations
uv run alembic upgrade head

# Start the API on port 5193
uv run python run.py
```

Notes:

- On Windows, always use `uv run python run.py`. Do not run `uvicorn src.main:app` directly; psycopg's async driver needs the SelectorEventLoop configured in `run.py`.
- With `APP_ENV=dev`, the application also creates missing tables and seeds development baseline data (regions, communities, categories, dictionaries, permissions, roles, the super admin, parameters, hot search terms). Production must use Alembic migrations and replace the seeded account.
- The default local administrator is `admin / Admin@2025`. This account is for local development only.
- To test with a physical phone, set `APP_HOST=0.0.0.0` in `web/backend/.env` and point the mobile `LOCAL_HOST` to your computer's LAN IP.

### 2. Start the admin console

```bash
cd web/frontend
npm install
npm run dev
```

Open <http://127.0.0.1:5192>. Vite proxies `/api` to `http://127.0.0.1:5193` using the backend `.env` values.

### 3. Run the mobile app

```bash
cd mobile
npm install
npm run check      # TypeScript + .uvue parse + link check + Vitest
```

Then:

1. Open HBuilderX 5.34 and import the `mobile/` directory.
2. If prompted, install the `compile-dart-sass` plugin.
3. Replace the placeholder DCloud AppID and WeChat Mini Program AppID in `manifest.json`.
4. Run to a browser, WeChat DevTools, Android device/emulator, or iOS/HarmonyOS toolchain.
5. H5 development server uses port **5191** with `strictPort`.

Environment switching is in `mobile/config/env.ts`:

- `CURRENT_ENV = 'local'` — connects to the unified backend at `http://127.0.0.1:5193/api/v1` (default).
- `CURRENT_ENV = 'dev'` — fully offline mock mode with seeded demo data.
- For Android emulators, set `LOCAL_HOST = '10.0.2.2'`; for physical devices, use the LAN IP.

## Ports and accounts

| Service | Address | Notes |
| --- | --- | --- |
| Mobile H5 dev server | <http://127.0.0.1:5191> | HBuilderX Web run |
| Admin console | <http://127.0.0.1:5192> | Vite dev server |
| Consumer API (C-end) | <http://127.0.0.1:5193/api/v1> | JWT Bearer |
| Admin API | <http://127.0.0.1:5193/api/v1/admin> | Cookie + CSRF |
| WebSocket | `ws://127.0.0.1:5193/api/v1/ws?token=<accessToken>` | IM, order, audit, notifications |
| Swagger / OpenAPI | <http://127.0.0.1:5193/docs> | Both contract groups are visible |
| Health checks | `/health/live`, `/health/ready` | Liveness and readiness |
| PostgreSQL | `127.0.0.1:5432` | Database `neighinn_platform` |
| Redis | `127.0.0.1:6379` | Sessions, SMS codes, cache |
| MinIO API / console | `127.0.0.1:9000` / `9001` | Buckets `ni-public`, `ni-private`, `ni-system` |
| RabbitMQ | `127.0.0.1:5672` / `15672` | Optional outbox delivery |
| Local admin account | `admin / Admin@2025` | Development only |

## Configuration

The backend reads `web/backend/.env` (gitignored; see `.env.example`). Key settings:

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_ENV` | `dev` | `dev` enables automatic table creation and seed data |
| `APP_HOST` / `APP_PORT` | `127.0.0.1` / `5193` | Use `0.0.0.0` for LAN/device access |
| `DATABASE_URL` | PostgreSQL DSN | SQLite (`sqlite+aiosqlite:///...`) works for tests and smoke runs |
| `REDIS_URL` | empty | Sessions and SMS code storage; falls back to in-memory if unavailable |
| `SMS_CODE_BACKEND` | `memory` | `redis` is recommended for restarts and multiple replicas |
| `CORS_ORIGINS` | 5191/5192/5173 | Add the mobile H5 and admin origins |
| `CORS_ORIGIN_REGEX` | dev only | Allows private-network origins for real-device H5 testing |
| `MINIO_*` | local MinIO | Public/private/system buckets and credentials |
| `AUTH_REQUIRE_2FA` | `false` in example | Force TOTP for admins that have bound it |
| `AUTH_ENFORCE_CSRF` | `true` | CSRF validation for admin writes |
| `ENABLE_SCHEDULER` | `true` | In-process outbox relay and timeout tasks |
| `SECRET_KEY` | dev placeholder | **Must be replaced in production with 32+ random bytes** |

Mobile environment values live in `mobile/config/env.ts` (`CURRENT_ENV`, `LOCAL_HOST`, `baseUrl`, `wsUrl`).

## API conventions

- **Envelope**: every JSON response is `{ "code": 0, "message": "...", "data": ..., "traceId": "..." }`; `code === 0` means success.
- **Authentication**:
  - Mobile: `Authorization: Bearer <accessToken>`; renew with `X-Refresh-Token`.
  - Admin: HttpOnly cookie session plus `X-CSRF-Token` double-submit validation (and TOTP when enabled).
- **Idempotency**: write requests carry `X-Idempotency-Key` (UUID); replaying the same key with a different body is rejected.
- **Pagination**: `page` / `pageSize` (default 20, max 50).
- **Time**: Unix milliseconds in transport; the database stores UTC.
- **Error codes** (common):

| Code | Meaning |
| --- | --- |
| `40001` | Validation failed |
| `40101` | Unauthenticated or token expired |
| `40301` | Forbidden / CSRF failure |
| `40302` | Missing certification or out of data scope |
| `40901` | Item already reserved, or request in progress |
| `40902` | Idempotency key reused with a different body |
| `40904` | Illegal state transition |
| `42201` | AI quality inspection failed |
| `42203` | Dual-review violation |
| `42204` | Unresolved reconciliation difference |
| `42901` | Rate limited |
| `50000` | Internal error |
| `50301` | SMS channel not configured |

- **WebSocket frames**: client sends `MSG_SEND`, `MSG_ACK`, `MSG_READ`, `PING`; server pushes `MSG_PUSH`, `ORDER_EVENT`, `AUDIT_EVENT`, `PONG`.

## Quality gates

Backend:

```bash
cd web/backend
uv run ruff check src tests run.py scripts
uv run pytest -q                 # 127 tests, SQLite-backed
```

Optional end-to-end smoke test against a running server:

```bash
# Terminal 1: start the backend (SQLite quick mode shown)
DEBUG=false APP_ENV=dev DATABASE_URL="sqlite+aiosqlite:///./dev-smoke.db" uv run python -c "
import asyncio, uvicorn
from src.main import app
asyncio.run(uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=5193)).serve())"

# Terminal 2: run the AC-01 certification loop
PYTHONIOENCODING=utf-8 uv run python scripts/smoke_e2e.py
```

Admin frontend:

```bash
cd web/frontend
npm run typecheck
npm run build
```

Mobile:

```bash
cd mobile
npm run check        # type-check + check:uvue + check:links + vitest (41 cases)
```

There is no CI configuration yet; `npm run check` and the backend pytest suite are the current quality gates.

## Documentation

| Document | Contents |
| --- | --- |
| [`CLAUDE.md`](CLAUDE.md) | Repository engineering guide, architecture rules, and conventions |
| [`docs/邻里小栈需求规格说明.md`](docs/邻里小栈需求规格说明.md) | Product requirements: roles, workflows, M01–M07 / W01–W08, AI capabilities, data, non-functional requirements |
| [`docs/邻里小栈UIUE设计设计规范-移动端.md`](docs/邻里小栈UIUE设计设计规范-移动端.md) | Mobile design tokens, components, dark mode, accessibility, performance |
| [`docs/邻里小栈双端业务闭环评估报告与优化改造方案.md`](docs/邻里小栈双端业务闭环评估报告与优化改造方案.md) | Dual-end business loop assessment and unified backend plan |
| [`mobile/docs/邻家小栈详细设计说明书-移动端.md`](mobile/docs/邻家小栈详细设计说明书-移动端.md) | Mobile implementation baseline: pages, components, tokens, APIs |
| [`mobile/docs/邻里小栈概要设计说明书-移动端.md`](mobile/docs/邻里小栈概要设计说明书-移动端.md) | Legacy mobile architecture and API contract reference |
| [`web/docs/邻里小栈后台管理系统详细设计说明书.md`](web/docs/邻里小栈后台管理系统详细设计说明书.md) | Admin console design: Figma restoration, pages, architecture, database, APIs, security, tests |
| [`mobile/README.md`](mobile/README.md) | Mobile app setup and implementation notes |
| [`web/backend/README.md`](web/backend/README.md) | Unified backend details, domain coverage, and development notes |
| [`web/frontend/README.md`](web/frontend/README.md) | Admin console setup and page map |

Mobile Figma Make prototype: <https://www.figma.com/make/OEw7s8EWAlGNNd4xnjZXkS/NeighInn%E2%80%8CMobile>.

## Current status and roadmap

| Area | Status |
| --- | --- |
| **Mobile** | 40 screens and 42 components implemented; offline mock flow and local backend wiring both work; HBuilderX 5.34 Web and WeChat Mini Program compilation verified; Android device verification pending |
| **Admin console** | First release implemented: login/session/CSRF, dashboard, community operations and management, certification review, finance and governance, notices/tasks, users/RBAC/parameters/audit, repairs, feedback; the report export page and four community extension pages are still placeholders |
| **Unified backend** | Phases 0–2 delivered: 70 tables, 9 migrations, 8 state machines, dual API contracts, WebSocket, 127 tests |
| **External services** | Mock adapters for payment, SMS, push, real-name verification, and AI quality inspection; production adapters pending |

Next up:

- Real channel adapters: payment, SMS, push, real-name verification, AI quality inspection.
- Complete 2FA enrollment UI in the admin console.
- Full `sys_pages` resource-page management.
- Automated reconciliation and alerting.
- Redis Pub/Sub for WebSocket fan-out across multiple replicas.
- Mobile: UTS plugins (payment, real-name, one-tap login), real-device Android verification, sharing/deep links, crash/tracking reporting.
- Mobile: dark mode, global elder-mode font scaling, and WeChat SVG compatibility regression.
- Linting, formatting, and CI pipelines.

## Contributing

1. Read `CLAUDE.md` and the relevant design document before changing a module.
2. Create a feature branch and keep commits focused; the repository uses Conventional Commit-style messages (`feat:`, `fix:`, `docs:`, `refactor:`, ...).
3. Run the relevant quality gates before opening a pull request.
4. Never commit `web/backend/.env`, `.claude/settings.local.json`, or any credentials.
5. For changes involving funds, certification, privacy, or moderation, verify the rules in SRS chapters 4/7/9 and the detailed design before coding.

Engineering guardrails:

- All state changes go through the state machines in `web/backend/src/domain/state.py`; never update `status` directly.
- Money is always integer cents (`*_cents`); balances are derived only from `ledger_entries`.
- Admin routes require `require_permission`; repositories apply `data_scope` filtering.
- Writes use idempotency keys; cross-end consistency relies on domain events and cache invalidation, not double writes.
- Mobile pages follow uni-app x Vapor constraints: `scroll-view` page roots, Flex only (no grid/gap/pseudo-elements), text styles on `<text>`, ASCII class names for WeChat WXSS.

## Security

Please report security vulnerabilities privately to the maintainers rather than opening a public issue. Do not include secrets, identity materials, or production data in reports.

## License

No license file is currently present in this repository. Unless a separate agreement states otherwise, all rights are reserved. Contact the maintainers for permission to use or redistribute the code.
