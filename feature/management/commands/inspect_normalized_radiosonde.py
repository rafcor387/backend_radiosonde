import json

from django.core.management.base import BaseCommand, CommandError

from feature.services.radiosonde_normalizer import (
    RadiosondeNormalizationError,
    normalize_radiosonde,
)
from feature.services.radiosonde_source import RadiosondeSourceError


class Command(BaseCommand):
    help = "Descarga, normaliza e inspecciona un radiosondeo por profile_id."

    def add_arguments(self, parser):
        parser.add_argument("profile_id", type=int)

    def handle(self, *args, **options):
        try:
            result = normalize_radiosonde(options["profile_id"]).general_response()
        except (RadiosondeSourceError, RadiosondeNormalizationError) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
