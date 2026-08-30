from django.contrib import admin

from .models import Auction, AuctionCategory, AuctionStatusLog


@admin.register(AuctionCategory)
class AuctionCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


class AuctionStatusLogInline(admin.TabularInline):
    model = AuctionStatusLog
    extra = 0
    readonly_fields = ("from_status", "to_status", "changed_by", "reason", "changed_at")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False  # status changes only via apps.auctions.services.transition()


@admin.register(Auction)
class AuctionAdmin(admin.ModelAdmin):
    list_display = ("title", "seller", "category", "status", "starting_price", "current_highest_bid", "start_time", "end_time")
    list_filter = ("status", "category")
    search_fields = ("title", "description", "seller__user__username")
    readonly_fields = ("current_highest_bid", "winner", "final_price", "reserve_met", "created_at", "updated_at")
    inlines = [AuctionStatusLogInline]


@admin.register(AuctionStatusLog)
class AuctionStatusLogAdmin(admin.ModelAdmin):
    list_display = ("auction", "from_status", "to_status", "changed_by", "changed_at")
    list_filter = ("to_status",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
