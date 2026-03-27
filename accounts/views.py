from django.contrib import messages
from django.contrib.auth.views import LoginView
from django.utils import timezone

from .forms import SalesAuthenticationForm


class SalesLoginView(LoginView):
    template_name = "auth/login.html"
    authentication_form = SalesAuthenticationForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        user = self.request.user
        user.last_access_at = timezone.now()
        user.last_ip = self.request.META.get("REMOTE_ADDR")
        user.save(update_fields=["last_access_at", "last_ip"])
        messages.success(self.request, f"Bem-vindo de volta, {user}.")
        return response

    def form_invalid(self, form):
        messages.error(self.request, "Credenciais invalidas. Tente novamente.")
        return super().form_invalid(form)
