from rest_framework import serializers


class PeriodQuerySerializer(serializers.Serializer):
    tgl_awal = serializers.DateField()
    tgl_akhir = serializers.DateField()

    def validate(self, attrs):
        if attrs["tgl_awal"] > attrs["tgl_akhir"]:
            raise serializers.ValidationError("tgl_awal tidak boleh setelah tgl_akhir.")
        return attrs


class VisitRowSerializer(serializers.Serializer):
    installation = serializers.ChoiceField(choices=("outpatient", "inpatient", "emergency"))
    payment_status = serializers.ChoiceField(choices=("general", "bpjs", "private_insurance", "social_assistance", "other"))
    count = serializers.IntegerField(min_value=0)


class DiseaseRowSerializer(serializers.Serializer):
    installation = serializers.ChoiceField(choices=("outpatient", "inpatient", "emergency"))
    icd10_code = serializers.CharField()
    name = serializers.CharField()
    patient_count = serializers.IntegerField(min_value=0)


class TouristRowSerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=("international", "domestic"))
    origin_code = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    origin = serializers.CharField(allow_blank=True)
    count = serializers.IntegerField(min_value=0)


class DiseaseGroupSerializer(serializers.Serializer):
    code = serializers.ChoiceField(choices=("cancer", "heart", "stroke", "uronephrology"))
    icd10_range = serializers.CharField()
    patient_count = serializers.IntegerField(min_value=0)


class HospitalSerializer(serializers.Serializer):
    province_code = serializers.CharField()
    province_name = serializers.CharField()
    code = serializers.CharField()
    name = serializers.CharField()


class ReportingPeriodSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=("month", "quarter", "semester", "year", "custom"))
    label = serializers.CharField()
    start = serializers.DateField()
    end = serializers.DateField()
    days = serializers.IntegerField(min_value=1)


class VisitEnvelopeSerializer(serializers.Serializer):
    period = ReportingPeriodSerializer()
    hospital = HospitalSerializer()
    results = VisitRowSerializer(many=True)


class DiseaseEnvelopeSerializer(serializers.Serializer):
    period = ReportingPeriodSerializer()
    hospital = HospitalSerializer()
    results = DiseaseRowSerializer(many=True)


class TouristEnvelopeSerializer(serializers.Serializer):
    period = ReportingPeriodSerializer()
    hospital = HospitalSerializer()
    results = TouristRowSerializer(many=True)


class DiseaseGroupEnvelopeSerializer(serializers.Serializer):
    period = ReportingPeriodSerializer()
    hospital = HospitalSerializer()
    results = DiseaseGroupSerializer(many=True)
