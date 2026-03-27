from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    full_name = models.CharField("nome", max_length=255)
    last_access_at = models.DateTimeField("ultimo acesso", null=True, blank=True)
    last_ip = models.GenericIPAddressField("ultimo IP", null=True, blank=True)

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
        ordering = ("username",)

    def save(self, *args, **kwargs):
        self.full_name = (self.full_name or "").strip()
        if self.full_name and not self.first_name and not self.last_name:
            parts = self.full_name.split()
            self.first_name = parts[0]
            if len(parts) > 1:
                self.last_name = " ".join(parts[1:])
        super().save(*args, **kwargs)

    def __str__(self):
        return self.full_name or self.username
