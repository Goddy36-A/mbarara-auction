# Delivery notes — read before running

This project is built in a sandbox with **no network access and no Django/
Postgres/Celery installed**, so the following have NOT been run here and
need to be run on your end before you rely on this code:

- `python manage.py makemigrations` — no migration files exist for any app
  yet (this has been true since Phase 3; not specific to this delivery).
  Run this once, then `python manage.py migrate`.
- `python manage.py test` — the test suite for every phase (including this
  one) is written but has never been executed. It's been checked for
  syntax errors and for consistency against the actual model/service field
  names, but not run.
- Any real Celery worker / Redis broker interaction — `CELERY_TASK_ALWAYS_EAGER`
  in `config/settings/testing.py` means the test suite exercises task code
  inline, but a real async run (`celery -A config worker`) hasn't been
  tried.

## This delivery (Phase 8 — Payments)

New/changed:
- `apps/payments/{models,services,views,urls,admin,tests}.py`
- `apps/audit/models.py` — added `PAYMENT_PENDING/RECEIVED/FAILED/REFUNDED`
  audit actions
- `apps/notifications/{models,services}.py` — added `PAYMENT_RECEIVED` /
  `PAYMENT_FAILED` events and their notify helpers
- `apps/bidding/services.py` — `close_auction()` now calls
  `create_pending_payment()` when a winner is determined
- `templates/payments/*.html`, nav links in `templates/base.html`
- `config/urls.py`, `README.md`

Worth double-checking once you can run it: the `CLOSED → SETTLED` auction
transition that `mark_paid()` triggers, and that `AuctionCategory`/`User`
role constants used in the new tests match your actual DB state (they're
copied from the existing test files' conventions, not re-verified against
a live database).

## On GitHub instead of a zip

I don't have a GitHub connector available in this workspace, and my sandbox's
bash tool has no network access — so even with a token pasted into chat, I
can't call the GitHub API directly to push commits from here. Two options:

1. Keep using zip delivery — I'll keep this file updated each phase with
   what's new and what's unverified.
2. If a GitHub (or generic git) connector gets added to this workspace's
   connector directory, tell me and I can use it instead — I'd search for
   it and let you pick it from a connector prompt rather than acting on a
   token pasted in plain chat text either way, since that's not a safe way
   to hand over a credential.


## Update — Phases 9, 10 and 12

- Migrations now exist and are committed (`disputes/0001`, `notifications/0002` are new).
- The full suite (225 tests) was run to completion on SQLite and passes. It has **not** been run on PostgreSQL, so row-locking behaviour (`select_for_update`) is untested under real concurrency.
- Bugs found and fixed by the new tests:
  - Password change and password reset crashed (`NoReverseMatch`) because the namespaced `accounts` URLs didn't match Django's default redirect names. Fixed with explicit `success_url`s and a namespaced reset-email template.
  - A bid amount of `NaN`, `Infinity`, an oversized value, or more than 2 decimal places caused a 500. `place_bid` now validates the amount.
  - Officers/admins opening `/bids/mine/`, `/payments/received/` or `/listings/mine/` got a 500 (no bidder/seller profile). They now see empty lists, and cannot open the create-listing form (403).
  - `test_inbox_only_shows_own_notifications` asserted the page never contains the letter "b"; it now checks for the other user's notification link.
- `requirements.txt` could not be installed as pinned (`crispy-bootstrap5==2026.9` needs `django-crispy-forms>=2.3` and `Django>=5.2`, while `django-celery-beat==2.6.0` caps Django below 5.2). Loosened to `django-crispy-forms>=2.6,<3` and `django-celery-beat>=2.8,<3`; `pip install -r requirements.txt` now resolves.

## Update: Auction Control dashboard, countdowns, new theme

- New migrations: `audit/0002` and `notifications/0003` (new action and event choices). Run `python manage.py migrate`.
- Automatic starting/closing is unchanged and still needs the two commands on a schedule. Public page loads deliberately do NOT start or close auctions (the project rule is that the server, not a visitor's browser, decides timing). Staff can start/close on demand from `/control/`.
- Countdowns are cosmetic. Bidding open/closed is always decided server-side at the moment a bid is placed.
- When a countdown reaches zero the page re-checks with the server after 3 seconds (20 seconds if it was already at zero on load, to avoid reload loops while waiting for the next sweep).
- The pause/resume feature does not freeze the clock: if the end time passes while paused, staff must set a new end time before resuming.
- Tested: 264 Python tests and a jsdom run of `countdown.js`. The visual theme has not been checked in a real browser from this environment, so give the pages a quick look on a phone and a laptop.
