from django.contrib import admin

from .models import (
    SimrsApiEndpoint,
    AdministrativeRegion,
    RegionAlias,
    InpatientIndicatorStandard,
    InpatientIndicatorAudit,
    InpatientIndicatorSource,
    MonthlyHealthIndicatorAudit,
    MonthlyHealthIndicatorSource,
    HealthIndicatorVerification,
    VerifiedInpatientIndicator,
    VerifiedMonthlyHealthIndicator,
    VerifiedHealthVisitRow,
    VerifiedTopDiseaseRow,
    VerifiedTouristVisitRow,
    VerifiedDiseaseGroupRow,
)


class RegionAliasInline(admin.TabularInline):
    model = RegionAlias
    extra = 0


@admin.register(AdministrativeRegion)
class AdministrativeRegionAdmin(admin.ModelAdmin):
    list_display = ("official_code", "name", "region_type", "parent", "island_group", "is_active")
    list_filter = ("region_type", "is_active", "island_group")
    search_fields = ("official_code", "name", "aliases__alias")
    inlines = (RegionAliasInline,)


@admin.register(InpatientIndicatorStandard)
class InpatientIndicatorStandardAdmin(admin.ModelAdmin):
    list_display = ("indicator", "policy_level", "minimum_value", "maximum_value", "effective_from", "effective_until", "is_active")
    list_filter = ("indicator", "policy_level", "is_active")
    readonly_fields = ("created_at", "updated_at", "updated_by")

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(SimrsApiEndpoint)
class SimrsApiEndpointAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "url", "is_active", "timeout_seconds", "updated_at")
    list_filter = ("is_active", "code")
    search_fields = ("name", "code", "url")
    readonly_fields = ("created_at", "updated_at", "updated_by")

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(MonthlyHealthIndicatorSource)
class MonthlyHealthIndicatorSourceAdmin(admin.ModelAdmin):
    list_display = ("period", "hospital_code", "hospital_name", "fetched_at")
    readonly_fields = ("source_data", "raw_response", "fetched_at")


class MonthlyHealthIndicatorAuditInline(admin.TabularInline):
    model = MonthlyHealthIndicatorAudit
    extra = 0
    readonly_fields = ("action", "before_data", "after_data", "actor", "created_at")
    can_delete = False


class HealthIndicatorVerificationInline(admin.TabularInline):
    model = HealthIndicatorVerification
    extra = 0
    readonly_fields = ("indicator_code", "status", "notes", "verified_by", "verified_at", "updated_at")
    can_delete = False


class VerifiedHealthVisitRowInline(admin.TabularInline):
    model = VerifiedHealthVisitRow
    extra = 0


class VerifiedTopDiseaseRowInline(admin.TabularInline):
    model = VerifiedTopDiseaseRow
    extra = 0


class VerifiedTouristVisitRowInline(admin.TabularInline):
    model = VerifiedTouristVisitRow
    extra = 0


class VerifiedDiseaseGroupRowInline(admin.TabularInline):
    model = VerifiedDiseaseGroupRow
    extra = 0


@admin.register(VerifiedMonthlyHealthIndicator)
class VerifiedMonthlyHealthIndicatorAdmin(admin.ModelAdmin):
    list_display = ("period", "status", "verified_by", "verified_at")
    list_filter = ("status",)
    readonly_fields = ("source", "period", "verified_data", "verified_by", "verified_at", "updated_at")
    inlines = (HealthIndicatorVerificationInline, VerifiedHealthVisitRowInline, VerifiedTopDiseaseRowInline, VerifiedTouristVisitRowInline, VerifiedDiseaseGroupRowInline, MonthlyHealthIndicatorAuditInline)


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
