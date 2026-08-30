"""
Closes LIVE auctions whose end_time has passed: determines the highest
valid bid, checks the reserve price, sets the winner, and transitions the
auction to CLOSED (Section 25).

Run periodically (cron every minute, or Celery beat in Phase 11):

    python manage.py close_ended_auctions
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.auctions.models import Auction
from apps.bidding.services import close_auction


class Command(BaseCommand):
    help = "Close LIVE auctions whose end_time has passed and determine winners."

    def handle(self, *args, **options):
        due = Auction.objects.filter(status=Auction.Status.LIVE, end_time__lte=timezone.now())
        count = 0
        for auction in due:
            closed = close_auction(auction)
            outcome = f"winner {closed.winner.username} at {closed.final_price}" if closed.winner else "no winner (reserve not met or no bids)"
            self.stdout.write(f"Closed auction #{closed.pk}: {closed.title} — {outcome}")
            count += 1
        self.stdout.write(self.style.SUCCESS(f"Done. {count} auction(s) closed."))
