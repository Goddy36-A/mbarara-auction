from django.contrib import admin

from .models import Dispute


@admin.register(Dispute)
class DisputeAdmin(admin.ModelAdmin):
    list_display = ("id", "auction", "category", "status", "outcome", "raised_by", "created_at")
    list_filter = ("status", "category", "outcome")
    search_fields = ("auction__title", "raised_by__username", "description")
    # Disputes change state only through apps.disputes.services so the auction
    # status, audit log and notifications stay consistent.
    readonly_fields = [f.name for f in Dispute._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
