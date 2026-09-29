import secrets
import unicodedata

from usuarios.models import User


class UsernameGenerationError(Exception):
    pass


class UsernameService:
    MAX_ATTEMPTS = 100

    @classmethod
    def generate(cls, name, paternal_surname, maternal_surname):
        prefix = "".join(
            [
                cls._initial(name),
                cls._initial(paternal_surname),
                cls._initial(maternal_surname),
            ]
        )

        for _ in range(cls.MAX_ATTEMPTS):
            suffix = f"{secrets.randbelow(1_000_000):06d}"
            username = f"{prefix}{suffix}"
            if not User.objects.filter(username__iexact=username).exists():
                return username

        raise UsernameGenerationError("Unable to generate a unique username.")

    @staticmethod
    def _initial(value):
        normalized = unicodedata.normalize("NFKD", value.strip())
        ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
        for character in ascii_value:
            if character.isalpha():
                return character.upper()
        raise UsernameGenerationError("Names must contain at least one letter.")
