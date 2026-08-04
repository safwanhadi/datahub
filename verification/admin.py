from django.contrib import admin

from .models import (
    DataSource,
    ImportBatch,
    InpatientIndicatorAudit,
    InpatientIndicatorSource,
    StagedRecord,
    VerificationAudit,
    VerifiedInpatientIndicator,
    VerifiedRecord,
)


@admin.register(DataSource)
class DataSourceAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active", "created_at")
    prepopulated_fields = {"code": ("name",)}


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = ("reference", "source", "status", "total_records", "created_at")
    list_filter = ("status", "source")


@admin.register(StagedRecord)
class StagedRecordAdmin(admin.ModelAdmin):
    list_display = ("source_key", "record_type", "status", "imported_at")
    list_filter = ("status", "record_type", "batch__source")
    search_fields = ("source_key",)
    readonly_fields = ("checksum",)


class AuditInline(admin.TabularInline):
    model = VerificationAudit
    extra = 0
    readonly_fields = ("action", "before_data", "after_data", "notes", "actor", "created_at")
    can_delete = False


@admin.register(VerifiedRecord)
class VerifiedRecordAdmin(admin.ModelAdmin):
    list_display = ("staged_record", "status", "verified_by", "updated_at")
    list_filter = ("status",)
    inlines = (AuditInline,)


@admin.register(InpatientIndicatorSource)
class InpatientIndicatorSourceAdmin(admin.ModelAdmin):
    list_display = ("period", "alos", "bor", "bto", "toi", "gdr", "ndr", "fetched_at")
    readonly_fields = [field.name for field in InpatientIndicatorSource._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class IndicatorAuditInline(admin.TabularInline):
    model = InpatientIndicatorAudit
    extra = 0
    readonly_fields = ("action", "before_data", "after_data", "actor", "created_at")
    can_delete = False


@admin.register(VerifiedInpatientIndicator)
class VerifiedInpatientIndicatorAdmin(admin.ModelAdmin):
    list_display = ("period", "status", "verified_by", "verified_at")
    list_filter = ("status",)
    inlines = (IndicatorAuditInline,)
