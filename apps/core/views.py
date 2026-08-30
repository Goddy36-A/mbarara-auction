from django.contrib.auth.decorators import login_required
from django.shortcuts import render


def home(request):
    """Public landing page — approved/live auctions will be listed here
    once the auctions app's browse view exists (Phase 5)."""
    return render(request, "core/home.html")


@login_required
def dashboard(request):
    """
    Role-aware dashboard landing spot. For now this renders a single
    template that branches on request.user.role; once the auctions/bidding
    apps exist, each role's real dashboard data (Section 29 of the design
    spec) will be assembled here or in dedicated per-role views.
    """
    return render(request, "core/dashboard.html")
