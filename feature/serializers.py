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
        help_text="Fecha del radiosondeo en formato YYYY-MM-DD."
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
