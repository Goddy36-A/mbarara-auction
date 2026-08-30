# Mbarara Online Auction System

Web-based auction platform for transparent bidding and price discovery in
Mbarara City. Built with Django + PostgreSQL, per the multi-phase System
Analysis & Design Specification (Phases 1-2, delivered separately as Word
documents) that this codebase implements.

## Project status

This repository currently implements **Phases 3-8**: Django Foundation,
Users/Roles, Auction Management (listings, categories, images, approval
workflow, lifecycle state machine), the Bidding Engine (concurrency-safe
bid placement, privacy-preserving bid history, automated closing & winner
determination), Notifications (in-app inbox with async delivery
plumbing), and Payments (status tracking only — no real gateway).

- [x] Project scaffold & modular app structure (`apps/*`)
- [x] Settings split: `base` / `development` / `testing` / `production`
- [x] PostgreSQL wired via `DATABASE_URL` (no hard-coded credentials)
- [x] Custom `User` model with role field (accounts app)
- [x] Registration, login, logout, password reset/change
- [x] Base templates (Bootstrap 5) + audit-log scaffolding
- [x] `SellerProfile` / `BidderProfile` models, auto-created on registration via signal
- [x] Verification workflow (PENDING/VERIFIED/REJECTED) with audit-logged approve/reject, officer/admin-only queue (UI + Django Admin actions)
- [x] Bidder account suspend/reactivate (`account_status`), feeds `BidderProfile.is_eligible_to_bid`
- [x] Shared role & object-level permission helpers (`apps/accounts/permissions.py`) for later apps to reuse
- [x] Auction & category models, immutable `AuctionStatusLog`, full lifecycle state machine (`apps/auctions/services.py`) enforced server-side with row locking
- [x] Listing create/edit (DRAFT-only) with image upload (type/size validated), submit-for-review
- [x] Officer/admin approval queue — approve auto-advances to SCHEDULED, reject requires a reason, both audit-logged
- [x] Public browse/search + detail pages that only ever expose publicly-visible statuses (drafts 404 for non-owners)
- [x] Bid model (immutable, unique per-auction sequence numbers), server-authoritative `place_bid()` with row-locking (`select_for_update`) concurrency control
- [x] Business rules enforced server-side: minimum bid/increment, seller self-bid block, eligibility (verified + active), time-window check
- [x] Anti-sniping auto-extension (configurable per auction)
- [x] Privacy-preserving bid history (anonymized "Bidder A/B/C" labels; bidders see their own bids as "You"; staff see real usernames)
- [x] Automated closing (`close_auction`) with reserve-price logic and deterministic tie-breaking by sequence number, plus `invalidate_bid` for admin correction with recomputed highest-bid
- [x] Management commands `activate_scheduled_auctions` and `close_ended_auctions` for cron/Celery-beat scheduling — never triggered by a browser request
- [x] `Notification` model (in-app inbox, read/unread state, event type, optional link back to the triggering object)
- [x] `apps/notifications/services.notify()` as the single creation entry point — synchronous in-app row + async `deliver_notification` Celery task for any future email/SMS channel
- [x] Event coverage: outbid, auction won, auction closed with no winner, auction went live, listing approved/rejected, account verified/rejected, bidder suspended/reactivated — wired into the existing accounts/auctions/bidding service layers at the same point each already writes an `AuditLog` entry
- [x] Inbox view + mark-one-read / mark-all-read endpoints, unread-count navbar badge via a context processor
- [x] `config/celery.py` wired up (Celery app instance, `django.conf:settings` config, autodiscovery) — was referenced by settings/requirements but not yet instantiated
- [x] Payments (status tracking only) — **Phase 8**
  - [x] `Payment` model, one row per won auction, auto-created (status PENDING) the moment `close_auction` determines a winner — never created ad hoc from a view
  - [x] `apps/payments/services.py`: `mark_paid` / `mark_failed` / `mark_refunded`, each requiring an `actor` (and a `reason` for failure/refund), audit-logged like every other state change in this project
  - [x] `mark_paid` advances the auction CLOSED → SETTLED and notifies both buyer and seller; `mark_failed` notifies the buyer
  - [x] Officer/admin payment-recording queue (`payments:queue`), plus read-only "my payments" (bidder) and "payments received" (seller) views
  - [x] No real payment gateway — `method`/`reference` are free-text fields an officer fills in after confirming payment happened out-of-band (per Phase 1 Project Assumption)
- [ ] Disputes — **Phase 9**
- [ ] Reports & analytics — **Phase 10**
- [ ] Security hardening pass & full audit coverage — **Phase 11**
- [ ] Test suite — **Phase 12**
- [ ] Deployment hardening — **Phase 13**

See `/docs` (Phase 1 and Phase 2 Word documents, exported separately) for
the full requirements, ERD, state machines, and security threat model this
implementation follows.

## Local setup

```bash
cp .env.example .env          # then edit .env with real local values
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
createdb mbarara_auction      # or let docker-compose's db service do it
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Or with Docker:

```bash
cp .env.example .env
docker-compose up --build
docker-compose exec web python manage.py migrate
docker-compose exec web python manage.py createsuperuser
```

Visit http://localhost:8000

## Running tests

```bash
DJANGO_SETTINGS_MODULE=config.settings.testing python manage.py test
```

## Scheduled tasks (auction activation & closing)

Auction timing is always server-authoritative (Section 55) — nothing in
the browser can open or close an auction. Two management commands drive
the lifecycle and are meant to run periodically (cron every minute, or as
Celery beat tasks once Celery is wired up in Phase 11):

```bash
python manage.py activate_scheduled_auctions   # SCHEDULED -> LIVE
python manage.py close_ended_auctions          # LIVE -> CLOSED, determines winner
```


## Project layout

```
config/settings/{base,development,testing,production}.py  — environment split
apps/accounts       — custom User model, auth, roles
apps/auctions        — auction lifecycle & categories        (Phase 5)
apps/listings         — listing creation & approval workflow  (Phase 5)
apps/bidding          — bid model & concurrency-safe service  (Phase 6)
apps/notifications  — in-app notifications                   (Phase 7)
apps/payments        — payment status tracking (no real gateway) (Phase 8)
apps/disputes        — dispute workflow                       (Phase 9)
apps/reports          — reporting & price-discovery analytics (Phase 10)
apps/audit            — immutable audit log                   (live now)
apps/core             — shared base models, home/dashboard    (live now)
```

## Contributing

- Business rules belong in a service layer, not in views or templates
  (see the System Design doc, Section 1).
- Every bid/auction-state decision must be validated server-side —
  never trust client-supplied timestamps or client-side countdowns.
- Run `flake8` before committing; keep migrations checked in.
