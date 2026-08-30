from django.contrib import admin

from .models import Payment
from .services import mark_paid


@admin.action(description="Mark selected pending payments as paid (generic — use the payment queue for a reference/method)")
def admin_mark_paid(modeladmin, request, queryset):
    for payment in queryset.filter(status=Payment.Status.PENDING):
        mark_paid(payment, actor=request.user, notes="Marked paid via Django Admin bulk action")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("auction", "amount", "status", "method", "paid_at", "recorded_by")
    list_filter = ("status", "method")
    search_fields = ("auction__title", "reference")
    readonly_fields = ("auction", "amount", "created_at")
    actions = [admin_mark_paid]

    def has_add_permission(self, request):
        return False  # only ever created via apps.payments.services.create_pending_payment
