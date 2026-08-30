from django.db import models


class TimeStampedModel(models.Model):
    """
    Abstract base adding created/updated timestamps. Every domain model in
    this project should inherit from this (directly or indirectly) so audit
    and reporting queries have a consistent, reliable time basis.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
