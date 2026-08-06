from rest_framework import serializers


class ExternalIndicatorResultSerializer(serializers.Serializer):
    periode = serializers.CharField()
    jenis_periode = serializers.CharField()
    tanggal_awal = serializers.DateField()
    tanggal_akhir = serializers.DateField()
    nilai = serializers.DecimalField(max_digits=10, decimal_places=2)
    diverifikasi_pada = serializers.DateTimeField(allow_null=True)


class ExternalIndicatorEnvelopeSerializer(serializers.Serializer):
    indikator = serializers.CharField()
    nama = serializers.CharField()
    satuan = serializers.CharField()
    count = serializers.IntegerField()
    results = ExternalIndicatorResultSerializer(many=True)


class ExternalVerifiedRecordSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    source_key = serializers.CharField()
    data = serializers.JSONField()
    verified_at = serializers.DateTimeField(allow_null=True)
    updated_at = serializers.DateTimeField()


class ExternalRecordEnvelopeSerializer(serializers.Serializer):
    record_type = serializers.CharField()
    count = serializers.IntegerField()
    results = ExternalVerifiedRecordSerializer(many=True)


class ExternalHealthIndicatorResultSerializer(serializers.Serializer):
    periode = serializers.CharField()
    jenis_periode = serializers.CharField()
    tanggal_awal = serializers.DateField()
    tanggal_akhir = serializers.DateField()
    data = serializers.JSONField(allow_null=True)
    diverifikasi_pada = serializers.DateTimeField(allow_null=True)


class ExternalHealthIndicatorEnvelopeSerializer(serializers.Serializer):
    kode = serializers.CharField()
    nama = serializers.CharField()
    satuan = serializers.CharField()
    count = serializers.IntegerField()
    results = ExternalHealthIndicatorResultSerializer(many=True)
