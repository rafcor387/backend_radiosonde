import os
from functools import lru_cache

import boto3
from botocore.config import Config
from django.core.exceptions import ImproperlyConfigured


@lru_cache(maxsize=1)
def get_r2_client():
    """Construye un cliente S3 limitado al acceso de Cloudflare R2."""
    endpoint_url = os.getenv("R2_ENDPOINT_URL")
    access_key_id = os.getenv("R2_ACCESS_KEY_ID")
    secret_access_key = os.getenv("R2_SECRET_ACCESS_KEY")

    missing = [
        name
        for name, value in (
            ("R2_ENDPOINT_URL", endpoint_url),
            ("R2_ACCESS_KEY_ID", access_key_id),
            ("R2_SECRET_ACCESS_KEY", secret_access_key),
        )
        if not value
    ]
    if missing:
        raise ImproperlyConfigured(
            f"Faltan variables de entorno para R2: {', '.join(missing)}"
        )

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name="auto",
        config=Config(
            connect_timeout=5,
            read_timeout=20,
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )
