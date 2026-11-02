"""Envía una carpeta anual al endpoint de carga por lotes (biblioteca estándar)."""

import argparse
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


MAX_BATCH_BYTES = 50 * 1024 * 1024


def make_batches(files, batch_size):
    batches, current, size = [], [], 0
    for path in files:
        file_size = path.stat().st_size
        if file_size > MAX_BATCH_BYTES:
            raise ValueError(f"{path.name} supera el límite total de un lote (50 MiB).")
        if current and (len(current) == batch_size or size + file_size > MAX_BATCH_BYTES):
            batches.append(current)
            current, size = [], 0
        current.append(path)
        size += file_size
    if current:
        batches.append(current)
    return batches


def multipart_body(year, files):
    boundary = "radiosondes-" + uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="year"\r\n\r\n{year}\r\n'.encode()]
    file_bytes = 0
    for path in files:
        if any(ord(character) < 32 for character in path.name):
            raise ValueError(f"Nombre de archivo inválido: {path.name!r}")
        filename = path.name.replace("\\", "\\\\").replace('"', '\\"')
        content = path.read_bytes()
        file_bytes += len(content)
        if file_bytes > MAX_BATCH_BYTES:
            raise ValueError("Los archivos cambiaron de tamaño y el lote supera 50 MiB.")
        parts.extend([
            (f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{filename}"\r\n'
             'Content-Type: text/tab-separated-values\r\n\r\n').encode("utf-8"),
            content, b"\r\n",
        ])
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, required=True, help="Carpeta cuyo nombre es el año, por ejemplo ../radiosonde_files/2018")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--report", type=Path, help="Destino del informe JSON de la carga")
    parser.add_argument("--dry-run", action="store_true", help="Muestra el plan sin leer el contenido, enviar archivos ni pedir token")
    args = parser.parse_args()
    folder = args.folder.resolve()
    if not folder.is_dir() or not folder.name.isascii() or not folder.name.isdigit() or not 1 <= int(folder.name) <= 9999:
        parser.error("--folder debe ser una carpeta existente cuyo nombre sea un año válido.")
    if not 1 <= args.batch_size <= 50 or args.timeout <= 0:
        parser.error("--batch-size debe estar entre 1 y 50 y --timeout debe ser positivo.")
    files = sorted(path for path in folder.iterdir() if path.is_file() and path.suffix.lower() == ".tsv")
    if not files:
        parser.error("La carpeta no contiene archivos TSV.")
    try:
        batches = make_batches(files, args.batch_size)
    except ValueError as exc:
        parser.error(str(exc))
    year = int(folder.name)
    print(f"Carpeta: {folder}\nAño: {year}\nArchivos: {len(files)}\nLotes: {len(batches)}")
    print(f"Destino: radiosondes/{year}/")
    if args.dry_run:
        print("Plan revisado. No se enviaron archivos.")
        return 0
    token = os.getenv("RADIOSONDE_UPLOAD_TOKEN") or getpass.getpass("Token de acceso JWT (no se guarda): ")
    if not token.strip():
        parser.error("Se requiere un token de acceso JWT.")
    report_path = args.report or Path(__file__).resolve().parents[1] / "output" / "uploads" / (
        f"{year}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}.json"
    )
    report = {"year": year, "bucket": "radiosondes", "total": len(files), "status": "incomplete", "batches": []}

    def save_report():
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    for index, batch in enumerate(batches, 1):
        try:
            body, content_type = multipart_body(year, batch)
            request = Request(
                args.api_url.rstrip("/") + "/feature/radiosondes/upload-folder/",
                data=body, headers={"Authorization": f"Bearer {token.strip()}", "Content-Type": content_type, "Accept": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=args.timeout) as response:
                result = json.load(response)
            if not isinstance(result, dict) or not {"uploaded", "skipped", "failed", "results"}.issubset(result):
                raise ValueError("El servidor devolvió un resultado inesperado.")
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1500] if isinstance(exc, HTTPError) else str(exc)
            report["error"] = {"batch": index, "detail": detail}
            save_report()
            print(f"No se completó el lote {index}. Informe: {report_path}\n{detail}")
            return 1
        report["batches"].append(result)
        save_report()
        print(f"Lote {index}/{len(batches)}: cargados={result['uploaded']}, omitidos={result['skipped']}, fallidos={result['failed']}")
    report["uploaded"] = sum(batch["uploaded"] for batch in report["batches"])
    report["skipped"] = sum(batch["skipped"] for batch in report["batches"])
    report["failed"] = sum(batch["failed"] for batch in report["batches"])
    report["status"] = "completed_with_errors" if report["failed"] else "completed"
    save_report()
    print(f"Informe: {report_path}")
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
