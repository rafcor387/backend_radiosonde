import json

from django.core.management.base import BaseCommand, CommandError

from feature.services.radiosonde_normalizer import RadiosondeNormalizationError
from feature.services.radiosonde_source import RadiosondeSourceError
from feature.services.radiosonde_stability import (
    RadiosondeStabilityError,
    classify_radiosonde_stability,
)


class Command(BaseCommand):
    help = "Clasifica la estabilidad de un radiosondeo almacenado en R2."

    def add_arguments(self, parser):
        parser.add_argument("profile_id", type=int)

    def handle(self, *args, **options):
        try:
            result = classify_radiosonde_stability(options["profile_id"])
        except (
            RadiosondeSourceError,
            RadiosondeNormalizationError,
            RadiosondeStabilityError,
        ) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
