import json

from django.core.management.base import BaseCommand, CommandError

from feature.services.radiosonde_source import (
    RadiosondeSourceError,
    inspect_radiosonde_source,
)


class Command(BaseCommand):
    help = "Descarga e inspecciona desde R2 el TSV asociado a un profile_id."

    def add_arguments(self, parser):
        parser.add_argument("profile_id", type=int)

    def handle(self, *args, **options):
        try:
            result = inspect_radiosonde_source(options["profile_id"])
        except RadiosondeSourceError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
