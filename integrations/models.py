from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class WebpicConfiguration(models.Model):
    name = models.CharField("nome", max_length=80, unique=True, default="Principal")
    api_company = models.CharField("empresa API", max_length=80, blank=True)
    api_token = models.CharField("token de integracao", max_length=255, blank=True)
    price_table_id = models.PositiveIntegerField("ID da tabela de preco", null=True, blank=True)
    import_products_without_price = models.BooleanField("importar produtos sem preco", default=False)
    employee_id = models.PositiveIntegerField("ID do funcionario", null=True, blank=True)
    representative_id = models.PositiveIntegerField("ID do representante", null=True, blank=True)
    client_group_id = models.PositiveIntegerField("ID do grupo de clientes", null=True, blank=True)
    current_account_id = models.PositiveIntegerField("ID da conta corrente", null=True, blank=True)
    access_token = models.TextField("access token", blank=True)
    access_token_expires_at = models.DateTimeField("expira em", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "configuracao Webpic"
        verbose_name_plural = "configuracoes Webpic"
        ordering = ("name",)

    def __str__(self):
        return self.name

    @classmethod
    def get_solo(cls):
        config, _ = cls.objects.get_or_create(pk=1, defaults={"name": "Principal"})
        return config

    @property
    def resolved_api_company(self):
        return settings.WEBPIC_API_COMPANY or self.api_company

    @property
    def resolved_api_token(self):
        return settings.WEBPIC_API_TOKEN or self.api_token

    @property
    def credentials_source(self):
        if settings.WEBPIC_API_COMPANY or settings.WEBPIC_API_TOKEN:
            return "env"
        return "database"

    @property
    def has_credentials(self):
        return bool(self.resolved_api_company and self.resolved_api_token)

    def access_token_is_valid(self):
        if not self.access_token or not self.access_token_expires_at:
            return False
        return self.access_token_expires_at > timezone.now() + timedelta(minutes=5)

    def missing_export_fields(self):
        fields = []
        if not self.resolved_api_company:
            fields.append("Empresa API")
        if not self.resolved_api_token:
            fields.append("Token de integracao")
        if not self.price_table_id:
            fields.append("Tabela de preco")
        if not self.employee_id:
            fields.append("Funcionario")
        if not self.representative_id:
            fields.append("Representante")
        if not self.client_group_id:
            fields.append("Grupo de clientes")
        if not self.current_account_id:
            fields.append("Conta corrente")
        return fields
