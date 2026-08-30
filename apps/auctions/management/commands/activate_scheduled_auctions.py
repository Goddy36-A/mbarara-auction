"""
Moves SCHEDULED auctions to LIVE once their start_time has passed.

Run periodically (cron every minute, or as a Celery beat task once Celery
is wired up in Phase 11) — never triggered by a browser request
(Section 55: the server, not the client, is authoritative on auction
timing).

    python manage.py activate_scheduled_auctions
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.auctions.models import Auction
from apps.auctions.services import activate_if_due


class Command(BaseCommand):
    help = "Activate SCHEDULED auctions whose start_time has passed."

    def handle(self, *args, **options):
        due = Auction.objects.filter(status=Auction.Status.SCHEDULED, start_time__lte=timezone.now())
        count = 0
        for auction in due:
            activate_if_due(auction)
            count += 1
            self.stdout.write(f"Activated auction #{auction.pk}: {auction.title}")
        self.stdout.write(self.style.SUCCESS(f"Done. {count} auction(s) activated."))
