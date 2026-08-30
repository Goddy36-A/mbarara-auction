from django.contrib import admin
from .models import Bid
from .services import invalidate_bid


@admin.action(description="Invalidate selected bids (generic reason — use disputes workflow for a specific one)")
def admin_invalidate(modeladmin, request, queryset):
    for bid in queryset.filter(status=Bid.Status.ACCEPTED):
        invalidate_bid(bid, actor=request.user, reason="Invalidated via Django Admin bulk action")


@admin.register(Bid)
class BidAdmin(admin.ModelAdmin):
    list_display = ("auction", "sequence_no", "bidder", "amount", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("auction__title", "bidder__user__username")
    readonly_fields = ("auction", "bidder", "amount", "sequence_no", "created_at")
    actions = [admin_invalidate]

    def has_add_permission(self, request):
        return False  # bids are only ever created via apps.bidding.services.place_bid

    def has_change_permission(self, request, obj=None):
        return False  # ...and invalidated only via the admin action above or the dispute workflow (Phase 9)
