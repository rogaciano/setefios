from django.db.models import Count

from .models import Company


def sales_context(request):
    return {
        "client_total": Company.objects.filter(is_active=True).aggregate(total=Count("id"))["total"] or 0,
    }
