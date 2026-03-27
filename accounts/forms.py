from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    PasswordResetForm,
    SetPasswordForm,
)


def _input(attrs=None):
    base = {
        "class": (
            "mt-2 block w-full rounded-2xl border border-stone-300 bg-white/80 "
            "px-4 py-3 text-sm text-stone-900 shadow-sm outline-none "
            "transition focus:border-orange-500 focus:ring-2 focus:ring-orange-200"
        )
    }
    if attrs:
        base.update(attrs)
    return base


class SalesAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label="Usuario",
        widget=forms.TextInput(
            attrs=_input(
                {
                    "placeholder": "Seu usuario",
                    "autofocus": True,
                    "autocomplete": "username",
                }
            )
        ),
    )
    password = forms.CharField(
        label="Senha",
        strip=False,
        widget=forms.PasswordInput(
            attrs=_input(
                {
                    "placeholder": "Sua senha",
                    "autocomplete": "current-password",
                }
            )
        ),
    )


class SalesPasswordChangeForm(PasswordChangeForm):
    old_password = forms.CharField(
        label="Senha atual",
        strip=False,
        widget=forms.PasswordInput(attrs=_input({"autocomplete": "current-password"})),
    )
    new_password1 = forms.CharField(
        label="Nova senha",
        strip=False,
        widget=forms.PasswordInput(attrs=_input({"autocomplete": "new-password"})),
    )
    new_password2 = forms.CharField(
        label="Confirmar nova senha",
        strip=False,
        widget=forms.PasswordInput(attrs=_input({"autocomplete": "new-password"})),
    )


class SalesPasswordResetForm(PasswordResetForm):
    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(
            attrs=_input(
                {
                    "placeholder": "voce@empresa.com.br",
                    "autocomplete": "email",
                }
            )
        ),
    )


class SalesSetPasswordForm(SetPasswordForm):
    new_password1 = forms.CharField(
        label="Nova senha",
        strip=False,
        widget=forms.PasswordInput(attrs=_input({"autocomplete": "new-password"})),
    )
    new_password2 = forms.CharField(
        label="Confirmar nova senha",
        strip=False,
        widget=forms.PasswordInput(attrs=_input({"autocomplete": "new-password"})),
    )
