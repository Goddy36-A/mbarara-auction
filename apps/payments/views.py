from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.accounts.permissions import BidderRequiredMixin, SellerRequiredMixin, StaffOrOfficerRequiredMixin

from .models import Payment
from .services import mark_failed, mark_paid, pending_payments


class PaymentQueueView(StaffOrOfficerRequiredMixin, View):
    """Officer/admin screen for recording payments confirmed out-of-band
    (Section-equivalent of the listing approval queue, but for payments)."""

    def get(self, request):
        return render(request, "payments/queue.html", {"payments": pending_payments()})


class RecordPaymentPaidView(StaffOrOfficerRequiredMixin, View):
    def post(self, request, pk):
        payment = get_object_or_404(Payment, pk=pk)
        try:
            mark_paid(
                payment, actor=request.user,
                method=request.POST.get("method", ""),
                reference=request.POST.get("reference", ""),
                notes=request.POST.get("notes", ""),
            )
            messages.success(request, f"Payment for '{payment.auction.title}' recorded as paid.")
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("payments:queue")


class RecordPaymentFailedView(StaffOrOfficerRequiredMixin, View):
    def post(self, request, pk):
        payment = get_object_or_404(Payment, pk=pk)
        reason = request.POST.get("reason", "")
        if not reason:
            messages.error(request, "A reason is required to mark a payment failed.")
            return redirect("payments:queue")
        try:
            mark_failed(payment, actor=request.user, reason=reason)
            messages.warning(request, f"Payment for '{payment.auction.title}' marked as failed.")
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("payments:queue")


class MyPaymentsView(BidderRequiredMixin, View):
    """A bidder's own record of what they owe/have paid for auctions won."""

    def get(self, request):
        payments = Payment.objects.filter(auction__winner=request.user).select_related("auction")
        return render(request, "payments/my_payments.html", {"payments": payments})


class SellerPaymentsView(SellerRequiredMixin, View):
    """A seller's own record of payments due/received on their auctions."""

    def get(self, request):
        payments = Payment.objects.filter(auction__seller=request.user.seller_profile).select_related("auction")
        return render(request, "payments/seller_payments.html", {"payments": payments})
