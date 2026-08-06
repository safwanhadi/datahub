from django.db import models
from django.utils import timezone


class ApiProduct(models.Model):
    code = models.SlugField("kode produk", max_length=120, unique=True)
    name = models.CharField("nama", max_length=160)
    description = models.TextField("keterangan", blank=True)
    required_scope = models.CharField("scope wajib", max_length=160)
    is_active = models.BooleanField("aktif", default=True)

    class Meta:
        ordering = ("code",)
        verbose_name = "produk API eksternal"
        verbose_name_plural = "produk API eksternal"

    def __str__(self):
        return self.code


class ExternalApiClient(models.Model):
    client_id = models.CharField("OAuth client ID", max_length=190, unique=True)
    name = models.CharField("nama aplikasi", max_length=160)
    is_active = models.BooleanField("aktif", default=True)
    requests_per_minute = models.PositiveIntegerField("request per menit", default=60)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "client API eksternal"
        verbose_name_plural = "client API eksternal"

    def __str__(self):
        return f"{self.name} ({self.client_id})"


class ExternalApiGrant(models.Model):
    client = models.ForeignKey(
        ExternalApiClient, on_delete=models.CASCADE, related_name="grants"
    )
    product = models.ForeignKey(ApiProduct, on_delete=models.CASCADE, related_name="grants")
    is_active = models.BooleanField("aktif", default=True)
    expires_at = models.DateTimeField("berakhir pada", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("client", "product"), name="unique_external_client_product"
            )
        ]
        verbose_name = "izin client eksternal"
        verbose_name_plural = "izin client eksternal"

    @property
    def is_valid(self):
        return self.is_active and (
            self.expires_at is None or self.expires_at > timezone.now()
        )

    def __str__(self):
        return f"{self.client.client_id} → {self.product.code}"


class ApiAccessLog(models.Model):
    client_id = models.CharField(max_length=190, db_index=True)
    product_code = models.CharField(max_length=120, db_index=True)
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=500)
    status_code = models.PositiveSmallIntegerField()
    remote_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "audit akses API"
        verbose_name_plural = "audit akses API"

    def __str__(self):
        return f"{self.client_id} {self.method} {self.path}"
