from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory

from .models import Company, Supplier, SupplierImportProfile, Participant, ParticipantCompany


BASE_INPUT_CLASS = (
    "mt-2 block w-full rounded-2xl border border-stone-300 bg-white "
    "px-4 py-3 text-sm text-stone-900 shadow-sm outline-none "
    "transition focus:border-orange-500 focus:ring-2 focus:ring-orange-200"
)

IMPORT_PARSER_CHOICES = [
    ("", "Qualquer layout conhecido"),
    ("FATURAMENTO_XLSX_BASIC", "Relatorio faturamento sem lote"),
    ("FATURAMENTO_XLSX_LOTE", "Relatorio faturamento com lote"),
    ("NFE_XML", "XML de NF-e"),
    ("PDF_PENDING", "PDF pendente de parser"),
]


def _text_widget(placeholder=""):
    return forms.TextInput(
        attrs={
            "class": BASE_INPUT_CLASS,
            "placeholder": placeholder,
        }
    )


def _email_widget(placeholder=""):
    return forms.EmailInput(
        attrs={
            "class": BASE_INPUT_CLASS,
            "placeholder": placeholder,
        }
    )


def _textarea_widget(rows=2, placeholder=""):
    return forms.Textarea(
        attrs={
            "class": BASE_INPUT_CLASS,
            "rows": rows,
            "placeholder": placeholder,
        }
    )


def _checkbox_widget():
    return forms.CheckboxInput(
        attrs={
            "class": "h-5 w-5 rounded border-stone-300 text-orange-600 focus:ring-orange-500"
        }
    )


def _select_widget():
    return forms.Select(attrs={"class": BASE_INPUT_CLASS})


class CompanyForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = (
            "legal_name",
            "trade_name",
            "cnpj",
            "state_registration",
            "phone",
            "email",
            "street",
            "number",
            "complement",
            "district",
            "postal_code",
            "city",
            "state",
            "is_active",
        )
        widgets = {
            "legal_name": _text_widget("Razao social do cliente"),
            "trade_name": _text_widget("Nome fantasia"),
            "cnpj": _text_widget("00.000.000/0000-00"),
            "state_registration": _text_widget("Inscricao estadual"),
            "phone": _text_widget("(00) 00000-0000"),
            "email": _email_widget("contato@cliente.com"),
            "street": _text_widget("Rua / Avenida"),
            "number": _text_widget("Numero"),
            "complement": _text_widget("Complemento"),
            "district": _text_widget("Bairro"),
            "postal_code": _text_widget("00000-000"),
            "city": _text_widget("Cidade"),
            "state": _text_widget("UF"),
            "is_active": _checkbox_widget(),
        }


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = (
            "trade_name",
            "cnpj",
            "contact_name",
            "phone",
            "email",
            "street",
            "number",
            "complement",
            "district",
            "postal_code",
            "city",
            "state",
            "is_active",
        )
        widgets = {
            "trade_name": _text_widget("Nome fantasia do fornecedor"),
            "cnpj": _text_widget("00.000.000/0000-00"),
            "contact_name": _text_widget("Responsavel ou contato principal"),
            "phone": _text_widget("(00) 00000-0000"),
            "email": _email_widget("contato@fornecedor.com"),
            "street": _text_widget("Rua / Avenida"),
            "number": _text_widget("Numero"),
            "complement": _text_widget("Complemento"),
            "district": _text_widget("Bairro"),
            "postal_code": _text_widget("00000-000"),
            "city": _text_widget("Cidade"),
            "state": _text_widget("UF"),
            "is_active": _checkbox_widget(),
        }


class SupplierImportProfileForm(forms.ModelForm):
    parser_key = forms.ChoiceField(
        label="Layout",
        required=False,
        choices=IMPORT_PARSER_CHOICES,
        widget=_select_widget(),
    )

    class Meta:
        model = SupplierImportProfile
        fields = (
            "name",
            "parser_key",
            "supplier_hint_pattern",
            "file_name_tokens",
            "notes",
            "is_active",
        )
        widgets = {
            "name": _text_widget("Ex.: Faturamento principal"),
            "supplier_hint_pattern": _text_widget("Nome que costuma aparecer no arquivo"),
            "file_name_tokens": _text_widget("Ex.: DANIEL, THAMI, FATURADOS"),
            "notes": _textarea_widget(rows=2, placeholder="Quando usar este layout"),
            "is_active": _checkbox_widget(),
        }

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("DELETE"):
            return cleaned_data

        values = [
            cleaned_data.get("name"),
            cleaned_data.get("parser_key"),
            cleaned_data.get("supplier_hint_pattern"),
            cleaned_data.get("file_name_tokens"),
            cleaned_data.get("notes"),
        ]
        if not any(values):
            return cleaned_data

        if not cleaned_data.get("supplier_hint_pattern") and not cleaned_data.get("file_name_tokens"):
            raise forms.ValidationError(
                "Informe o nome lido do arquivo ou palavras do nome do arquivo para o perfil de importacao."
            )

        return cleaned_data


class BaseSupplierImportProfileFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        signatures = set()

        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue
            if form.cleaned_data.get("DELETE"):
                continue

            values = [
                form.cleaned_data.get("name"),
                form.cleaned_data.get("parser_key"),
                form.cleaned_data.get("supplier_hint_pattern"),
                form.cleaned_data.get("file_name_tokens"),
                form.cleaned_data.get("notes"),
            ]
            if not any(values):
                continue

            signature = (
                (form.cleaned_data.get("parser_key") or "").strip().upper(),
                (form.cleaned_data.get("supplier_hint_pattern") or "").strip().upper(),
                (form.cleaned_data.get("file_name_tokens") or "").strip().upper(),
            )
            if signature in signatures:
                raise forms.ValidationError("Existe mais de um perfil de importacao com a mesma assinatura para este fornecedor.")
            signatures.add(signature)


class ParticipantForm(forms.ModelForm):
    class Meta:
        model = Participant
        fields = (
            "name",
            "email",
            "phone",
            "notes",
            "is_representative",
            "commission_percentage",
            "is_active",
        )
        widgets = {
            "name": _text_widget("Nome do contato"),
            "email": _email_widget("email@contato.com"),
            "phone": _text_widget("(00) 00000-0000"),
            "notes": _textarea_widget(rows=3, placeholder="Observações sobre o contato"),
            "is_representative": _checkbox_widget(),
            "commission_percentage": _text_widget("0.00"),
            "is_active": _checkbox_widget(),
        }


class ParticipantCompanyForm(forms.ModelForm):
    company = forms.ModelChoiceField(
        queryset=Company.objects.filter(is_active=True).order_by("trade_name", "legal_name"),
        required=True,
        widget=_select_widget(),
        label="Cliente"
    )
    
    class Meta:
        model = ParticipantCompany
        fields = ("company", "is_primary",)
        widgets = {
            "is_primary": _checkbox_widget(),
        }


class BaseParticipantCompanyFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        primary_count = 0
        
        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue
            if form.cleaned_data.get("DELETE"):
                continue
            if form.cleaned_data.get("is_primary"):
                primary_count += 1
        
        if primary_count > 1:
            raise forms.ValidationError("Apenas um contato pode ser marcado como principal.")


ParticipantCompanyFormSet = inlineformset_factory(
    Participant,
    ParticipantCompany,
    form=ParticipantCompanyForm,
    formset=BaseParticipantCompanyFormSet,
    extra=1,
    can_delete=True,
)


SupplierImportProfileFormSet = inlineformset_factory(
    Supplier,
    SupplierImportProfile,
    form=SupplierImportProfileForm,
    formset=BaseSupplierImportProfileFormSet,
    extra=2,
    can_delete=True,
)
