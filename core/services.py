from .models import Company


def get_active_client_total():
    return Company.objects.filter(is_active=True).count()
