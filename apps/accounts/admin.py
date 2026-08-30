from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import BidderProfile, SellerProfile, User
from .services import reactivate_bidder, reject_profile, suspend_bidder, verify_profile


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("username", "email", "role", "is_verified", "is_active", "date_joined")
    list_filter = ("role", "is_verified", "is_active", "is_staff")
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Auction platform", {"fields": ("role", "phone_number", "is_verified")}),
    )


@admin.action(description="Verify selected profiles")
def admin_verify(modeladmin, request, queryset):
    for profile in queryset:
        verify_profile(profile, actor=request.user, reason="Verified via Django Admin bulk action")


@admin.action(description="Reject selected profiles (requires individual reason — use the detail view)")
def admin_reject(modeladmin, request, queryset):
    for profile in queryset:
        reject_profile(profile, actor=request.user, reason="Rejected via Django Admin bulk action")


@admin.register(SellerProfile)
class SellerProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "city", "verification_status", "verified_at", "created_at")
    list_filter = ("verification_status", "city")
    search_fields = ("user__username", "user__email", "phone")
    actions = [admin_verify, admin_reject]
    readonly_fields = ("verified_at", "verified_by", "created_at", "updated_at")


@admin.action(description="Suspend selected bidder accounts")
def admin_suspend(modeladmin, request, queryset):
    for profile in queryset:
        suspend_bidder(profile, actor=request.user, reason="Suspended via Django Admin bulk action")


@admin.action(description="Reactivate selected bidder accounts")
def admin_reactivate(modeladmin, request, queryset):
    for profile in queryset:
        reactivate_bidder(profile, actor=request.user)


@admin.register(BidderProfile)
class BidderProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "verification_status", "account_status", "verified_at", "created_at")
    list_filter = ("verification_status", "account_status")
    search_fields = ("user__username", "user__email", "phone")
    actions = [admin_verify, admin_reject, admin_suspend, admin_reactivate]
    readonly_fields = ("verified_at", "verified_by", "created_at", "updated_at")
