from django.db import models
from django.utils import timezone


class Company(models.Model):
    legal_name = models.CharField("razao social", max_length=255)
    trade_name = models.CharField("nome fantasia", max_length=255, blank=True)
    cnpj = models.CharField(max_length=18, unique=True)
    state_registration = models.CharField("inscricao estadual", max_length=30, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField("telefone", max_length=30, blank=True)
    street = models.CharField("rua", max_length=255, blank=True)
    number = models.CharField("numero", max_length=20, blank=True)
    complement = models.CharField(max_length=120, blank=True)
    district = models.CharField("bairro", max_length=120, blank=True)
    postal_code = models.CharField("CEP", max_length=12, blank=True)
    city = models.CharField("cidade", max_length=120, blank=True)
    state = models.CharField("UF", max_length=2, blank=True)
    is_active = models.BooleanField("ativo", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "cliente"
        verbose_name_plural = "clientes"
        ordering = ("trade_name", "legal_name")

    def __str__(self):
        return self.trade_name or self.legal_name


class Supplier(models.Model):
    trade_name = models.CharField("nome fantasia", max_length=255)
    cnpj = models.CharField(max_length=18, unique=True)
    contact_name = models.CharField("contato", max_length=255, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField("telefone", max_length=30, blank=True)
    street = models.CharField("rua", max_length=255, blank=True)
    number = models.CharField("numero", max_length=20, blank=True)
    complement = models.CharField(max_length=120, blank=True)
    district = models.CharField("bairro", max_length=120, blank=True)
    postal_code = models.CharField("CEP", max_length=12, blank=True)
    city = models.CharField("cidade", max_length=120, blank=True)
    state = models.CharField("UF", max_length=2, blank=True)
    is_active = models.BooleanField("ativo", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "fornecedor"
        verbose_name_plural = "fornecedores"
        ordering = ("trade_name",)

    def save(self, *args, **kwargs):
        for field in ("trade_name", "contact_name", "street", "district", "city", "state"):
            value = getattr(self, field, "")
            setattr(self, field, (value or "").strip().upper())
        super().save(*args, **kwargs)

    def __str__(self):
        return self.trade_name


class SupplierImportProfile(models.Model):
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.CASCADE,
        related_name="import_profiles",
        verbose_name="fornecedor",
    )
    name = models.CharField("nome do perfil", max_length=120, blank=True)
    parser_key = models.CharField("layout", max_length=60, blank=True)
    supplier_hint_pattern = models.CharField("nome lido no arquivo", max_length=255, blank=True)
    file_name_tokens = models.CharField("palavras do nome do arquivo", max_length=255, blank=True)
    notes = models.CharField("observacoes", max_length=255, blank=True)
    is_active = models.BooleanField("ativo", default=True)
    match_count = models.PositiveIntegerField("usos", default=0)
    last_matched_at = models.DateTimeField("ultimo uso", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "perfil de importacao do fornecedor"
        verbose_name_plural = "perfis de importacao do fornecedor"
        ordering = ("supplier__trade_name", "name", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("supplier", "parser_key", "supplier_hint_pattern", "file_name_tokens"),
                name="unique_supplier_import_profile_signature",
            )
        ]

    def save(self, *args, **kwargs):
        for field in ("name", "parser_key", "supplier_hint_pattern", "file_name_tokens"):
            value = getattr(self, field, "")
            setattr(self, field, (value or "").strip().upper())
        self.notes = (self.notes or "").strip()
        super().save(*args, **kwargs)

    def register_match(self):
        self.match_count += 1
        self.last_matched_at = timezone.now()
        self.save(update_fields=["match_count", "last_matched_at", "updated_at"])

    def __str__(self):
        return self.name or f"{self.supplier.trade_name} | {self.parser_key or 'QUALQUER LAYOUT'}"


class Participant(models.Model):
    name = models.CharField("nome", max_length=255)
    email = models.EmailField(blank=True)
    phone = models.CharField("telefone", max_length=30, blank=True)
    notes = models.TextField("observacoes", blank=True)
    is_representative = models.BooleanField("representante", default=False)
    commission_percentage = models.DecimalField(
        "comissao (%)",
        max_digits=5,
        decimal_places=2,
        default=0,
    )
    is_active = models.BooleanField("ativo", default=True)
    companies = models.ManyToManyField(
        Company,
        through="ParticipantCompany",
        related_name="participants",
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "participante"
        verbose_name_plural = "participantes"
        ordering = ("name",)

    def __str__(self):
        return self.name


class ParticipantCompany(models.Model):
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE)
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    is_primary = models.BooleanField("principal", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "vinculo cliente-participante"
        verbose_name_plural = "vinculos cliente-participante"
        constraints = [
            models.UniqueConstraint(
                fields=("participant", "company"),
                name="unique_participant_company",
            )
        ]

    def __str__(self):
        return f"{self.participant} - {self.company}"
