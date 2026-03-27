from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path, reverse_lazy

from accounts.forms import (
    SalesPasswordChangeForm,
    SalesPasswordResetForm,
    SalesSetPasswordForm,
)
from accounts.views import SalesLoginView
from core.views import DashboardView, HomeRedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", HomeRedirectView.as_view(), name="home"),
    path("entrar/", SalesLoginView.as_view(), name="login"),
    path("sair/", auth_views.LogoutView.as_view(), name="logout"),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("cadastros/", include("core.urls")),
    path(
        "senha/alterar/",
        auth_views.PasswordChangeView.as_view(
            form_class=SalesPasswordChangeForm,
            template_name="registration/password_change_form.html",
            success_url=reverse_lazy("password_change_done"),
        ),
        name="password_change",
    ),
    path(
        "senha/alterada/",
        auth_views.PasswordChangeDoneView.as_view(
            template_name="registration/password_change_done.html"
        ),
        name="password_change_done",
    ),
    path(
        "senha/esqueci/",
        auth_views.PasswordResetView.as_view(
            form_class=SalesPasswordResetForm,
            template_name="registration/password_reset_form.html",
            email_template_name="registration/password_reset_email.html",
            subject_template_name="registration/password_reset_subject.txt",
            success_url=reverse_lazy("password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "senha/email-enviado/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="registration/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "senha/redefinir/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            form_class=SalesSetPasswordForm,
            template_name="registration/password_reset_confirm.html",
            success_url=reverse_lazy("password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "senha/redefinida/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="registration/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
    path("vendas/", include("sales.urls")),
    path("integracoes/", include("integrations.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

