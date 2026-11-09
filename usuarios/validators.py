import unicodedata

from rest_framework import serializers


def validate_person_name(value):
    """Allow letters, their combining accents, and spaces between name parts."""
    words = [word for word in value.split(" ") if word]
    if not words or any(
        not word[0].isalpha()
        or any(
            not character.isalpha()
            and not unicodedata.category(character).startswith("M")
            for character in word
        )
        for word in words
    ):
        raise serializers.ValidationError(
            "Solo se permiten letras y espacios, incluidas tildes y ñ.",
            code="invalid_name",
        )
