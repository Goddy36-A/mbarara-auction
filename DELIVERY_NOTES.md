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
