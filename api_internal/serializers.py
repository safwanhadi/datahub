from rest_framework import serializers


class InternalRoomIndicatorSerializer(serializers.Serializer):
    kode_ruang = serializers.CharField()
    nama_ruang = serializers.CharField()
    ruang_khusus = serializers.BooleanField()
    jumlah_bed = serializers.IntegerField()
    hari_perawatan = serializers.IntegerField()
    pasien_keluar = serializers.IntegerField()
    alos = serializers.DecimalField(max_digits=10, decimal_places=2)
    bor = serializers.DecimalField(max_digits=10, decimal_places=2)
    bto = serializers.DecimalField(max_digits=10, decimal_places=2)
    toi = serializers.DecimalField(max_digits=10, decimal_places=2)
    gdr = serializers.DecimalField(max_digits=10, decimal_places=2)
    ndr = serializers.DecimalField(max_digits=10, decimal_places=2)


class InternalIndicatorSerializer(serializers.Serializer):
    periode = serializers.DateField()
    jenis_periode = serializers.CharField()
    tanggal_awal = serializers.DateField()
    tanggal_akhir = serializers.DateField()
    status = serializers.CharField()
    alos = serializers.DecimalField(max_digits=10, decimal_places=2)
    bor = serializers.DecimalField(max_digits=10, decimal_places=2)
    bto = serializers.DecimalField(max_digits=10, decimal_places=2)
    toi = serializers.DecimalField(max_digits=10, decimal_places=2)
    gdr = serializers.DecimalField(max_digits=10, decimal_places=2)
    ndr = serializers.DecimalField(max_digits=10, decimal_places=2)
    notes = serializers.CharField()
    verified_by = serializers.CharField(allow_null=True)
    verified_at = serializers.DateTimeField(allow_null=True)
    updated_at = serializers.DateTimeField()
    ruangan = InternalRoomIndicatorSerializer(many=True)


class InternalIndicatorEnvelopeSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    results = InternalIndicatorSerializer(many=True)


class InternalMonthlyHealthSerializer(serializers.Serializer):
    periode = serializers.DateField()
    jenis_periode = serializers.CharField()
    tanggal_awal = serializers.DateField()
    tanggal_akhir = serializers.DateField()
    status = serializers.CharField()
    hospital_code = serializers.CharField()
    hospital_name = serializers.CharField()
    data = serializers.JSONField()
    verified_by = serializers.CharField(allow_null=True)
    verified_at = serializers.DateTimeField(allow_null=True)


class InternalMonthlyHealthEnvelopeSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    results = InternalMonthlyHealthSerializer(many=True)
