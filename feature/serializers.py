from datetime import datetime, timezone as datetime_timezone

from rest_framework import serializers

from .models import RadiosondeProfile


class RadiosondeUploadSerializer(serializers.Serializer):
    # Definimos que esperamos un ARCHIVO
    file = serializers.FileField(
        required=True,
        help_text="Sube aquí tu archivo .tsv con los datos del radiosondeo."
    )


class RadiosondeSearchQuerySerializer(serializers.Serializer):
    date = serializers.DateField(
        help_text="Fecha exacta en formato YYYY-MM-DD.",
    )
    time = serializers.TimeField(
        required=False,
        input_formats=["%H:%MZ", "%H:%M"],
        help_text="Hora UTC opcional, por ejemplo 00:00Z o 12:00Z.",
    )


class RadiosondeSearchResultSerializer(serializers.ModelSerializer):
    profile_id = serializers.IntegerField(source="id", read_only=True)
    time = serializers.SerializerMethodField()
    observed_at = serializers.SerializerMethodField()

    class Meta:
        model = RadiosondeProfile
        fields = ("profile_id", "date", "time", "observed_at")

    def get_time(self, obj):
        if obj.time is None:
            return None
        return obj.time.strftime("%H:%MZ")

    def get_observed_at(self, obj):
        observed_at = obj.observed_at

        # En la primera versión se permite que observed_at sea nulo. Si existe
        # date + time, construimos el instante UTC que necesita el agente.
        if observed_at is None and obj.time is not None:
            observed_at = datetime.combine(
                obj.date,
                obj.time,
                tzinfo=obj.time.tzinfo or datetime_timezone.utc,
            )

        if observed_at is None:
            return None

        return serializers.DateTimeField().to_representation(observed_at)


class RadiosondeSearchResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField(min_value=0)
    radiosondes = RadiosondeSearchResultSerializer(many=True)


class RadiosondeReportRequestSerializer(serializers.Serializer):
    start_date = serializers.DateField(
        help_text="Fecha inicial inclusiva en formato YYYY-MM-DD."
    )
    end_date = serializers.DateField(
        required=False,
        help_text="Fecha final inclusiva. Si se omite, usa start_date.",
    )
    time = serializers.TimeField(
        required=False,
        allow_null=True,
        input_formats=["%H:%MZ", "%H:%M"],
        help_text="Hora UTC opcional para filtrar los lanzamientos.",
    )

    def validate(self, attrs):
        start_date = attrs["start_date"]
        end_date = attrs.get("end_date") or start_date
        if end_date < start_date:
            raise serializers.ValidationError(
                "end_date no puede ser anterior a start_date."
            )
        if (end_date - start_date).days + 1 > 366:
            raise serializers.ValidationError(
                "La primera versión admite intervalos de hasta 366 días."
            )
        attrs["end_date"] = end_date
        return attrs
