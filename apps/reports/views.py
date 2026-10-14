from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import render
from django.views import View

from apps.accounts.permissions import StaffOrOfficerRequiredMixin

from .services import (
    auctions_in_range, build_summary, parse_date, payments_in_range, write_auctions_csv, write_payments_csv,
)


class _RangeMixin:
    def get_range(self, request):
        raw_from, raw_to = request.GET.get("from", ""), request.GET.get("to", "")
        date_from, date_to = parse_date(raw_from), parse_date(raw_to)
        invalid = (raw_from and not date_from) or (raw_to and not date_to)
        if date_from and date_to and date_from > date_to:
            invalid = True
        if invalid:
            return None, None, False
        return date_from, date_to, True


class ReportsDashboardView(StaffOrOfficerRequiredMixin, _RangeMixin, View):
    def get(self, request):
        date_from, date_to, ok = self.get_range(request)
        if not ok:
            messages.error(request, "Enter valid dates (YYYY-MM-DD), with the start before the end.")
        summary = build_summary(date_from, date_to)
        return render(request, "reports/dashboard.html", {
            "s": summary, "date_from": date_from, "date_to": date_to,
            "from_value": date_from.isoformat() if date_from else "",
            "to_value": date_to.isoformat() if date_to else "",
        })


class AuctionsCsvView(StaffOrOfficerRequiredMixin, _RangeMixin, View):
    def get(self, request):
        date_from, date_to, _ = self.get_range(request)
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="auctions.csv"'
        write_auctions_csv(response, auctions_in_range(date_from, date_to))
        return response


class PaymentsCsvView(StaffOrOfficerRequiredMixin, _RangeMixin, View):
    def get(self, request):
        date_from, date_to, _ = self.get_range(request)
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="payments.csv"'
        write_payments_csv(response, payments_in_range(date_from, date_to))
        return response
