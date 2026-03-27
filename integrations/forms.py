from django import forms

from .models import WebpicConfiguration


INPUT_CLASS = (
    "mt-2 block w-full rounded-2xl border border-stone-300 bg-white px-4 py-3 "
    "text-sm text-stone-900 shadow-sm outline-none transition "
    "focus:border-orange-500 focus:ring-2 focus:ring-orange-200"
)


def _number_widget(placeholder=""):
    return forms.NumberInput(
        attrs={
            "class": INPUT_CLASS,
            "placeholder": placeholder,
            "min": "0",
            "step": "1",
        }
    )


def _checkbox_widget():
    return forms.CheckboxInput(
        attrs={
            "class": "h-5 w-5 rounded border-stone-300 text-orange-600 focus:ring-orange-500",
        }
    )


class WebpicConfigurationForm(forms.ModelForm):
    class Meta:
        model = WebpicConfiguration
        fields = (
            "price_table_id",
            "import_products_without_price",
            "employee_id",
            "representative_id",
            "client_group_id",
            "current_account_id",
        )
        widgets = {
            "price_table_id": _number_widget(),
            "import_products_without_price": _checkbox_widget(),
            "employee_id": _number_widget(),
            "representative_id": _number_widget(),
            "client_group_id": _number_widget(),
            "current_account_id": _number_widget(),
        }
