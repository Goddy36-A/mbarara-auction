from django.db import models

from apps.auctions.models import Auction


def auction_image_path(instance, filename):
    return f"auctions/{instance.auction_id}/{filename}"


class AuctionImage(models.Model):
    """Section 15/44: images belong to the listing-creation workflow, with
    upload validation handled in the form (allowed types/size), not just
    trusted from the client."""

    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to=auction_image_path)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"Image for {self.auction.title}"
