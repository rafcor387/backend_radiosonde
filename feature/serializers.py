from rest_framework import serializers

class RadiosondeUploadSerializer(serializers.Serializer):
    # Definimos que esperamos un ARCHIVO
    file = serializers.FileField(
        required=True,
        help_text="Sube aquí tu archivo .tsv con los datos del radiosondeo."
    )