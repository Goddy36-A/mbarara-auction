"""Fill the database with realistic demo data for Mbarara City.

    python manage.py seed_demo            # create demo users, categories and auctions
    python manage.py seed_demo --reset    # remove the demo data, then create it again
    python manage.py seed_demo --clear    # remove the demo data only

Everything goes through the same services the website uses (approve, go live,
place_bid, close), so audit logs, notifications and status history are real.
Safe to run more than once: existing demo records are skipped.
For development only: it refuses to run when DEBUG is off unless --force is given.
"""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import ProtectedError
from django.utils import timezone

from apps.accounts.models import BidderProfile, SellerProfile, User, VerificationStatus
from apps.auctions import scheduling, services
from apps.auctions.models import Auction, AuctionCategory
from apps.bidding.services import BidRejected, close_auction, place_bid

PASSWORD = "Demo@12345"

CATEGORIES = [
    "Livestock", "Coffee & Produce", "Land & Property", "Vehicles",
    "Electronics", "Furniture", "Farm Equipment", "Art & Crafts",
]

OFFICER = ("officer1", "Grace", "Natukunda", "0700000001")
SELLERS = [
    ("seller_kakoba", "Moses", "Tumusiime", "0700000011", "Kakoba"),
    ("seller_ruharo", "Annet", "Kyomuhendo", "0700000012", "Ruharo"),
    ("seller_nyamitanga", "Peter", "Byaruhanga", "0700000013", "Nyamitanga"),
    ("seller_rwampara", "Sarah", "Asiimwe", "0700000014", "Rwampara"),
]
BIDDERS = [  # (username, first, last, phone, verified?)
    ("bidder_amos", "Amos", "Mugisha", "0700000021", True),
    ("bidder_brenda", "Brenda", "Nuwagaba", "0700000022", True),
    ("bidder_charles", "Charles", "Atuhaire", "0700000023", True),
    ("bidder_diana", "Diana", "Twinomugisha", "0700000024", True),
    ("bidder_edwin", "Edwin", "Ainembabazi", "0700000025", True),
    ("bidder_pending", "Patience", "Kobusingye", "0700000026", False),  # shows up in the verification queue
]

# title, category, seller, location, start price, reserve, increment, state,
# start offset (hours), end offset (hours), number of bids, extension minutes, description
AUCTIONS = [
    # ---- LIVE ----
    ("Ankole long-horn bull, 4 years", "Livestock", "seller_kakoba", "Kashari", 1800000, 2200000, 50000, "LIVE", -20, 0.2, 6, 5,
     "Healthy Ankole long-horn bull with the breed's long, curved horns. Vaccinated and dewormed. Viewing at the Kashari farm by appointment."),
    ("Grade-A Arabica coffee, 2 tonnes", "Coffee & Produce", "seller_ruharo", "Bwizibwera", 9500000, 11000000, 200000, "LIVE", -30, 0.75, 4, 5,
     "Two tonnes of sun-dried, hand-sorted Arabica, moisture-tested. Stored in a dry warehouse in Bwizibwera."),
    ("Friesian dairy cow in calf", "Livestock", "seller_rwampara", "Rwampara", 2200000, 2800000, 50000, "LIVE", -12, 3, 5, 0,
     "Third-lactation Friesian, about 18 litres a day, due to calve in 6 weeks. Records available."),
    ("Bajaj Boxer boda boda 2021", "Vehicles", "seller_kakoba", "Kamukuzi", 3800000, 4200000, 100000, "LIVE", -6, 26, 3, 0,
     "Well-kept 2021 Bajaj Boxer, new tyres, valid insurance. Logbook in hand."),
    ("Dell Latitude laptop, i5, 16GB RAM", "Electronics", "seller_nyamitanga", "Mbarara City", 1450000, None, 25000, "LIVE", -4, 50, 2, 0,
     "Business laptop, 512GB SSD, battery holds about 4 hours. Charger included."),
    ("Mahogany dining set, 6 seats", "Furniture", "seller_nyamitanga", "Nyamitanga", 2600000, 3000000, 50000, "LIVE", -2, 72, 0, 0,
     "Solid mahogany table with six upholstered chairs, hand-made in Mbarara. No bids yet."),
    ("Walking tractor with plough", "Farm Equipment", "seller_rwampara", "Bwizibwera", 8500000, 9500000, 250000, "LIVE", -8, 120, 1, 0,
     "Two-wheel walking tractor with plough attachment, serviced this year. Ideal for 1 to 5 acres."),
    # ---- SCHEDULED ----
    ("Quarter-acre plot with title, Nyamitanga", "Land & Property", "seller_ruharo", "Nyamitanga", 35000000, 40000000, 1000000, "SCHEDULED", 0.5, 72, 0, 0,
     "Quarter-acre plot with a land title, 300 m from the tarmac road. Boundaries marked, utilities nearby."),
    ("Toyota Premio 2012", "Vehicles", "seller_kakoba", "Kamukuzi", 24000000, 26000000, 500000, "SCHEDULED", 6, 96, 0, 5,
     "Toyota Premio 2012, automatic, low mileage, one owner. Inspection welcome."),
    ("Three-bedroom house, Ruharo", "Land & Property", "seller_ruharo", "Ruharo", 180000000, 200000000, 5000000, "SCHEDULED", 4, 168, 0, 10,
     "Three-bedroom house on a fenced plot with water tank and solar. Close to schools and the hospital."),
    ("Matooke truck load (Bogoya)", "Coffee & Produce", "seller_rwampara", "Rwampara", 1400000, None, 50000, "SCHEDULED", 24, 30, 0, 0,
     "A full truck of fresh matooke, harvested the day before the sale."),
    ("Hand-woven Banyankole basket set", "Art & Crafts", "seller_kakoba", "Kakoba", 180000, None, 10000, "SCHEDULED", 48, 96, 0, 0,
     "Set of five traditional baskets woven by a women's cooperative in Kakoba."),
    # ---- PAUSED ----
    ("Samsung 55-inch Smart TV", "Electronics", "seller_nyamitanga", "Mbarara City", 1100000, None, 25000, "PAUSED", -10, 10, 3, 0,
     "Samsung 55-inch 4K Smart TV, boxed, one year old."),
    # ---- CLOSED ----
    ("Pyrethrum sprayers, 20 litre (set of 10)", "Farm Equipment", "seller_rwampara", "Isingiro Road", 650000, 700000, 20000, "CLOSED", -80, -2, 4, 0,
     "Ten knapsack sprayers, 20 litres each, new in carton."),
    ("Mountain bike, 21-speed", "Vehicles", "seller_kakoba", "Kakoba", 450000, 800000, 20000, "CLOSED", -90, -5, 3, 0,
     "21-speed mountain bike, recently serviced. Closed without meeting the reserve."),
    # ---- WAITING FOR APPROVAL / DRAFT ----
    ("Solar water heater, 200 litre", "Electronics", "seller_ruharo", "Ruharo", 1200000, None, 25000, "SUBMITTED", 24, 96, 0, 0,
     "Roof-mounted 200-litre solar water heater, includes pipes and fittings."),
    ("Goat herd, 12 does", "Livestock", "seller_rwampara", "Rwampara", 3000000, 3500000, 100000, "SUBMITTED", 24, 120, 0, 0,
     "Twelve Boer-cross does, healthy and vaccinated."),
    ("Antique wooden stool set", "Furniture", "seller_nyamitanga", "Nyamitanga", 300000, None, 10000, "DRAFT", 24, 96, 0, 0,
     "Draft listing: the seller has not submitted this one yet."),
]
BID_STEPS = [1, 2, 1, 3, 1, 2]


class Command(BaseCommand):
    help = "Create demo categories, users and auctions for Mbarara City (development only)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Remove the demo data first, then re-create it.")
        parser.add_argument("--clear", action="store_true", help="Remove the demo data and stop.")
        parser.add_argument("--force", action="store_true", help="Allow running when DEBUG is off.")

    def handle(self, *args, **opts):
        if not settings.DEBUG and not opts["force"]:
            raise CommandError("seed_demo is for development. DEBUG is off; use --force only if you are sure.")
        if opts["reset"] or opts["clear"]:
            self.clear()
            if opts["clear"]:
                return
        now = timezone.now()
        with transaction.atomic():
            cats = {n: AuctionCategory.objects.get_or_create(name=n)[0] for n in CATEGORIES}
            officer = self.make_officer()
            sellers = self.make_sellers(officer)
            bidders = self.make_bidders(officer)
        created = 0
        for spec in AUCTIONS:
            if self.make_auction(spec, now, cats, sellers, bidders, officer):
                created += 1
        self.summary(created)

    # ---------- users ----------
    def _user(self, username, first, last, phone, role, **extra):
        user, new = User.objects.get_or_create(username=username, defaults={
            "first_name": first, "last_name": last, "phone_number": phone, "role": role,
            "email": f"{username}@example.com", **extra})
        if new:
            user.set_password(PASSWORD)
            user.save()
        return user

    def make_officer(self):
        u, f, l, p = OFFICER
        return self._user(u, f, l, p, User.Role.OFFICER, is_staff=True, is_verified=True)

    def make_sellers(self, officer):
        out = {}
        for u, f, l, p, city in SELLERS:
            user = self._user(u, f, l, p, User.Role.SELLER, is_verified=True)
            SellerProfile.objects.filter(user=user).update(
                city=city, phone=p, verification_status=VerificationStatus.VERIFIED,
                verified_at=timezone.now(), verified_by=officer)
            out[u] = SellerProfile.objects.get(user=user)
        return out

    def make_bidders(self, officer):
        out = {}
        for u, f, l, p, verified in BIDDERS:
            user = self._user(u, f, l, p, User.Role.BIDDER, is_verified=verified)
            BidderProfile.objects.filter(user=user).update(
                location="Mbarara", phone=p,
                verification_status=VerificationStatus.VERIFIED if verified else VerificationStatus.PENDING,
                verified_at=timezone.now() if verified else None, verified_by=officer if verified else None)
            out[u] = User.objects.get(pk=user.pk)  # fresh copy: no stale cached profile
        return out

    # ---------- auctions ----------
    def make_auction(self, spec, now, cats, sellers, bidders, officer):
        (title, cat, seller_key, loc, start_p, reserve, inc, state, s_off, e_off, n_bids, ext, desc) = spec
        seller = sellers[seller_key]
        if Auction.objects.filter(title=title, seller=seller).exists():
            return False
        # Closed auctions are built as live ones that end later, so bids are accepted
        end_offset = 1 if state == "CLOSED" else e_off
        auction = Auction.objects.create(
            seller=seller, category=cats[cat], title=title, description=desc, location=loc,
            starting_price=Decimal(start_p), reserve_price=Decimal(reserve) if reserve else None,
            min_increment=Decimal(inc), extension_minutes=ext,
            start_time=now + timedelta(hours=s_off), end_time=now + timedelta(hours=end_offset))
        if state == "DRAFT":
            return True
        services.submit_for_review(auction, actor=seller.user)
        if state == "SUBMITTED":
            return True
        auction = services.approve(auction, actor=officer)            # -> SCHEDULED
        if state == "SCHEDULED":
            return True
        services.transition(auction, Auction.Status.LIVE, actor=officer, reason="Seeded demo auction")
        self.place_bids(auction, start_p, inc, n_bids, bidders)
        auction.refresh_from_db()
        if state == "PAUSED":
            scheduling.pause(auction, actor=officer, reason="Seller asked to update the photos")
        elif state == "CLOSED":
            Auction.objects.filter(pk=auction.pk).update(end_time=now + timedelta(hours=e_off))
            close_auction(Auction.objects.get(pk=auction.pk), actor=officer, reason="Seeded: auction ended")
        return True

    def place_bids(self, auction, start_p, inc, n, bidders):
        names = [b[0] for b in BIDDERS if b[4]]
        amount, who = Decimal(start_p), 0
        for k in range(n):
            if k:
                amount += Decimal(inc) * BID_STEPS[k % len(BID_STEPS)]
            try:
                place_bid(auction, bidder_user=bidders[names[who % len(names)]], amount=amount)
            except BidRejected as exc:
                self.stderr.write(f"  bid skipped on '{auction.title}': {exc}")
            who += 1

    # ---------- clean up ----------
    def clear(self):
        names = [OFFICER[0]] + [s[0] for s in SELLERS] + [b[0] for b in BIDDERS]
        try:
            with transaction.atomic():
                Auction.objects.filter(seller__user__username__in=names).delete()
                User.objects.filter(username__in=names).delete()
        except ProtectedError:
            raise CommandError("Some demo records are linked to payments or disputes and cannot be removed. "
                               "Run 'python start.py --reset' to wipe the whole development database instead.")
        self.stdout.write("Demo data removed.")

    def summary(self, created):
        counts = {s: Auction.objects.filter(status=s).count() for s in
                  ("LIVE", "SCHEDULED", "PAUSED", "CLOSED", "SUBMITTED", "DRAFT")}
        self.stdout.write(self.style.SUCCESS(f"\nDemo data ready: {created} new auction(s) created."))
        self.stdout.write("Auctions now: " + ", ".join(f"{k.lower()} {v}" for k, v in counts.items()))
        self.stdout.write(f"\nAll demo accounts use the password: {PASSWORD}")
        self.stdout.write("  Officer  : officer1   (opens /control/ and the approval queue)")
        self.stdout.write("  Sellers  : " + ", ".join(s[0] for s in SELLERS))
        self.stdout.write("  Bidders  : " + ", ".join(b[0] for b in BIDDERS if b[4]))
        self.stdout.write("  Pending  : bidder_pending (shows in the verification queue)")
