from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time as time_type
import hashlib
from io import BytesIO
import json
import os

from botocore.exceptions import BotoCoreError, ClientError
from django.db import close_old_connections, transaction
from django.utils import timezone
import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image,
    KeepTogether,
    LongTable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from feature.models import RadiosondeProfile, RadiosondeReport

from .r2_client import get_r2_client
from .radiosonde_normalizer import normalize_radiosonde
from .radiosonde_stability import classify_normalized_stability
from .radiosonde_thermodynamics import calculate_thermodynamics
from .radiosonde_wind import analyze_normalized_wind


REPORT_VERSION = "v1"
REPORT_RENDER_REVISION = 2
MAX_REPORT_RANGE_DAYS = 366
MAX_REPORT_BYTES = 25 * 1024 * 1024
_EXECUTOR = ThreadPoolExecutor(
    max_workers=max(1, int(os.getenv("RADIOSONDE_REPORT_WORKERS", "2"))),
    thread_name_prefix="radiosonde-report",
)


class RadiosondeReportError(Exception):
    """Error controlado al crear, procesar o recuperar un informe."""


def create_radiosonde_report(
    start_date: date,
    end_date: date,
    requested_time: time_type | None = None,
) -> tuple[RadiosondeReport, bool]:
    """Crea o reutiliza un trabajo y programa su generación en segundo plano."""
    if end_date < start_date:
        raise RadiosondeReportError(
            "La fecha final no puede ser anterior a la fecha inicial."
        )
    if (end_date - start_date).days + 1 > MAX_REPORT_RANGE_DAYS:
        raise RadiosondeReportError(
            f"La primera versión admite intervalos de hasta {MAX_REPORT_RANGE_DAYS} días."
        )

    profiles = RadiosondeProfile.objects.filter(
        date__range=(start_date, end_date)
    ).order_by("date", "time", "observed_at", "id")
    if requested_time is not None:
        profiles = profiles.filter(time=requested_time)

    catalog = list(
        profiles.values("id", "date", "time", "bucket", "object_key")
    )
    if not catalog:
        raise RadiosondeReportError(
            "No existen radiosondeos para el intervalo y la hora solicitados."
        )

    fingerprint = _fingerprint(catalog, start_date, end_date, requested_time)
    reusable = (
        RadiosondeReport.objects.filter(
            fingerprint=fingerprint,
            report_version=REPORT_VERSION,
            status__in=(
                RadiosondeReport.Status.PENDING,
                RadiosondeReport.Status.PROCESSING,
                RadiosondeReport.Status.READY,
            ),
        )
        .order_by("-created_at")
        .first()
    )
    if reusable is not None:
        return reusable, True

    report = RadiosondeReport.objects.create(
        start_date=start_date,
        end_date=end_date,
        time=requested_time,
        status=RadiosondeReport.Status.PENDING,
        fingerprint=fingerprint,
        report_version=REPORT_VERSION,
        bucket=catalog[0]["bucket"],
        filename=_report_filename(start_date, end_date, requested_time),
        profile_count=len(catalog),
    )
    transaction.on_commit(lambda: enqueue_radiosonde_report(report.pk))
    return report, False


def enqueue_radiosonde_report(report_id: int) -> None:
    """Entrega el trabajo al ejecutor local de la primera versión."""
    _EXECUTOR.submit(_run_report_job, report_id)


def report_descriptor(report: RadiosondeReport, cached: bool = False) -> dict:
    status_path = f"/api/radiosonde-reports/{report.pk}"
    file_path = f"{status_path}/file"
    return {
        "type": "radiosonde_report",
        "report_id": report.pk,
        "status": report.status,
        "start_date": report.start_date.isoformat(),
        "end_date": report.end_date.isoformat(),
        "time": report.time.strftime("%H:%MZ") if report.time else None,
        "profile_count": report.profile_count,
        "processed_count": report.processed_count,
        "failed_count": report.failed_count,
        "progress_percent": _progress_percent(report),
        "status_path": status_path,
        "view_path": file_path if report.status == RadiosondeReport.Status.READY else None,
        "download_path": (
            f"{file_path}?download=true"
            if report.status == RadiosondeReport.Status.READY
            else None
        ),
        "filename": report.filename,
        "content_type": "application/pdf",
        "size_bytes": report.size_bytes,
        "report_version": report.report_version,
        "cached": cached,
        "summary": report.summary,
        "error": report.error or None,
    }


def load_report_pdf(report_id: int) -> tuple[RadiosondeReport, bytes]:
    try:
        report = RadiosondeReport.objects.get(pk=report_id)
    except RadiosondeReport.DoesNotExist as exc:
        raise RadiosondeReportError(
            f"No existe un informe con report_id={report_id}."
        ) from exc
    if report.status != RadiosondeReport.Status.READY or not report.object_key:
        raise RadiosondeReportError("El informe todavía no está listo para descargar.")

    try:
        response = get_r2_client().get_object(
            Bucket=report.bucket,
            Key=report.object_key,
        )
    except (ClientError, BotoCoreError) as exc:
        raise RadiosondeReportError(
            "No se pudo recuperar el informe almacenado en R2."
        ) from exc

    body = response["Body"]
    try:
        pdf_bytes = body.read(MAX_REPORT_BYTES + 1)
    finally:
        body.close()
    if len(pdf_bytes) > MAX_REPORT_BYTES:
        raise RadiosondeReportError(
            f"El PDF supera el límite de {MAX_REPORT_BYTES} bytes."
        )
    return report, pdf_bytes


def generate_report_pdf(
    report: RadiosondeReport,
    rows: list[dict],
    summary: dict,
) -> bytes:
    """Genera el documento PDF enteramente en memoria con ReportLab."""
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.55 * cm,
        leftMargin=1.55 * cm,
        topMargin=1.8 * cm,
        bottomMargin=1.6 * cm,
        title=report.filename,
        author="Sistema de análisis de radiosondeos - La Paz",
        subject="Informe meteorológico de radiosondeos",
    )
    styles = _report_styles()
    story = []

    story.extend(_cover_story(report, summary, styles))
    story.append(PageBreak())
    story.extend(_executive_summary_story(report, summary, styles))

    chart = _render_temporal_chart(rows)
    if chart is not None:
        story.append(Spacer(1, 0.25 * cm))
        story.append(Paragraph("Evolución temporal", styles["SectionTitle"]))
        story.append(Image(chart, width=17.2 * cm, height=10.0 * cm))

    story.append(Spacer(1, 0.3 * cm))
    story.extend(_extremes_story(summary, styles))
    story.append(Spacer(1, 0.45 * cm))
    story.extend(_inventory_story(rows, styles))
    story.append(Spacer(1, 0.4 * cm))
    story.extend(_methodology_story(styles))

    document.build(
        story,
        onFirstPage=_draw_page_frame,
        onLaterPages=_draw_page_frame,
    )
    return buffer.getvalue()


def _run_report_job(report_id: int) -> None:
    close_old_connections()
    try:
        with transaction.atomic():
            report = RadiosondeReport.objects.select_for_update().get(pk=report_id)
            if report.status not in (
                RadiosondeReport.Status.PENDING,
                RadiosondeReport.Status.FAILED,
            ):
                return
            report.status = RadiosondeReport.Status.PROCESSING
            report.started_at = timezone.now()
            report.completed_at = None
            report.error = ""
            report.processed_count = 0
            report.failed_count = 0
            report.save(
                update_fields=(
                    "status",
                    "started_at",
                    "completed_at",
                    "error",
                    "processed_count",
                    "failed_count",
                )
            )

        rows = _analyze_report_profiles(report)
        successful = [row for row in rows if row["status"] != "failed"]
        if not successful:
            details = "; ".join(
                f"perfil {row['profile_id']}: "
                f"{(row.get('warnings') or ['error desconocido'])[0]}"
                for row in rows[:3]
            )
            raise RadiosondeReportError(
                "Ningún radiosondeo pudo normalizarse para construir el informe. "
                f"Detalle: {details}"
            )
        summary = _aggregate_summary(rows)
        pdf_bytes = generate_report_pdf(report, rows, summary)
        if len(pdf_bytes) > MAX_REPORT_BYTES:
            raise RadiosondeReportError(
                f"El PDF generado supera el límite de {MAX_REPORT_BYTES} bytes."
            )

        object_key = (
            f"derived/reports/{REPORT_VERSION}/"
            f"{report.start_date.isoformat()}_{report.end_date.isoformat()}/"
            f"{report.fingerprint}.pdf"
        )
        _store_pdf(report, object_key, pdf_bytes)
        RadiosondeReport.objects.filter(pk=report_id).update(
            status=RadiosondeReport.Status.READY,
            object_key=object_key,
            size_bytes=len(pdf_bytes),
            summary=summary,
            processed_count=len(rows),
            failed_count=sum(row["status"] != "ok" for row in rows),
            completed_at=timezone.now(),
            error="",
        )
    except Exception as exc:
        RadiosondeReport.objects.filter(pk=report_id).update(
            status=RadiosondeReport.Status.FAILED,
            completed_at=timezone.now(),
            error=str(exc)[:4000],
        )
    finally:
        close_old_connections()


def _analyze_report_profiles(report: RadiosondeReport) -> list[dict]:
    profiles = RadiosondeProfile.objects.filter(
        date__range=(report.start_date, report.end_date)
    ).order_by("date", "time", "observed_at", "id")
    if report.time is not None:
        profiles = profiles.filter(time=report.time)

    rows = []
    for record in profiles.iterator(chunk_size=20):
        row = {
            "profile_id": record.pk,
            "date": record.date.isoformat(),
            "time": record.time.strftime("%H:%MZ") if record.time else None,
            "observed_at": (
                record.observed_at.isoformat().replace("+00:00", "Z")
                if record.observed_at
                else None
            ),
            "status": "ok",
            "warnings": [],
        }
        try:
            normalized = normalize_radiosonde(record.pk)
            general = normalized.general_response()
            row.update(
                {
                    "quality": general["quality"].get("status"),
                    "levels": general["coverage"].get("levels"),
                    "surface_temperature_c": general["surface"].get(
                        "temperature_c"
                    ),
                    "surface_relative_humidity_pct": general["surface"].get(
                        "relative_humidity_pct"
                    ),
                    "surface_pressure_hpa": general["surface"].get(
                        "pressure_hpa"
                    ),
                }
            )
            row["warnings"].extend(general["quality"].get("warnings", []))
        except Exception as exc:
            row["status"] = "failed"
            row["warnings"].append(f"Normalización: {exc}")
            rows.append(row)
            _update_progress(report.pk, rows)
            continue

        thermodynamics = None
        try:
            thermodynamics = calculate_thermodynamics(normalized)
            surface = thermodynamics.parcels["surface_based"]
            mixed = thermodynamics.parcels["mixed_layer_50hpa"]
            row.update(
                {
                    "sb_cape_j_kg": surface.get("cape_j_kg"),
                    "sb_cin_j_kg": surface.get("cin_j_kg"),
                    "ml_cape_j_kg": mixed.get("cape_j_kg"),
                    "ml_cin_j_kg": mixed.get("cin_j_kg"),
                    "precipitable_water_mm": thermodynamics.indices.get(
                        "precipitable_water_mm"
                    ),
                    "lifted_index_c": thermodynamics.indices.get(
                        "lifted_index_c"
                    ),
                }
            )
        except Exception as exc:
            row["status"] = "partial"
            row["warnings"].append(f"Termodinámica: {exc}")

        try:
            stability = classify_normalized_stability(
                normalized,
                thermodynamics=thermodynamics,
            )
            row["stability_code"] = stability["classification"]["code"]
            row["stability_label"] = stability["classification"]["label"]
        except Exception as exc:
            row["status"] = "partial"
            row["warnings"].append(f"Estabilidad: {exc}")

        try:
            wind = analyze_normalized_wind(normalized)
            row["maximum_wind_ms"] = wind["maximum_wind"].get("speed_ms")
            shear = wind["bulk_shear"].get("0_6km")
            row["bulk_shear_0_6km_ms"] = (
                shear.get("speed_ms") if shear else None
            )
        except Exception as exc:
            row["status"] = "partial"
            row["warnings"].append(f"Viento: {exc}")

        rows.append(row)
        _update_progress(report.pk, rows)
    return rows


def _update_progress(report_id: int, rows: list[dict]) -> None:
    RadiosondeReport.objects.filter(pk=report_id).update(
        processed_count=len(rows),
        failed_count=sum(row["status"] != "ok" for row in rows),
    )


def _aggregate_summary(rows: list[dict]) -> dict:
    usable = [row for row in rows if row["status"] != "failed"]
    stability_counts = Counter(
        row.get("stability_label") or "No disponible" for row in usable
    )
    metrics = {}
    for key in (
        "surface_temperature_c",
        "surface_relative_humidity_pct",
        "sb_cape_j_kg",
        "ml_cape_j_kg",
        "precipitable_water_mm",
        "maximum_wind_ms",
        "bulk_shear_0_6km_ms",
    ):
        values = [row.get(key) for row in usable]
        finite = [float(value) for value in values if _finite(value)]
        metrics[key] = (
            {
                "minimum": round(min(finite), 2),
                "mean": round(float(np.mean(finite)), 2),
                "maximum": round(max(finite), 2),
                "available_count": len(finite),
            }
            if finite
            else None
        )

    extremes = {}
    for key in (
        "surface_temperature_c",
        "ml_cape_j_kg",
        "maximum_wind_ms",
        "bulk_shear_0_6km_ms",
    ):
        candidates = [row for row in usable if _finite(row.get(key))]
        if candidates:
            maximum = max(candidates, key=lambda item: float(item[key]))
            minimum = min(candidates, key=lambda item: float(item[key]))
            extremes[key] = {
                "maximum": _extreme_payload(maximum, key),
                "minimum": _extreme_payload(minimum, key),
            }

    return {
        "requested_profiles": len(rows),
        "successful_profiles": sum(row["status"] == "ok" for row in rows),
        "partial_profiles": sum(row["status"] == "partial" for row in rows),
        "failed_profiles": sum(row["status"] == "failed" for row in rows),
        "stability_distribution": dict(stability_counts),
        "metrics": metrics,
        "extremes": extremes,
    }


def _cover_story(report, summary, styles):
    time_text = report.time.strftime("%H:%MZ") if report.time else "Todas las horas"
    return [
        Spacer(1, 2.2 * cm),
        Paragraph("INFORME DE RADIOSONDEOS", styles["CoverTitle"]),
        Spacer(1, 0.35 * cm),
        Paragraph("Estación 85201 - La Paz", styles["CoverSubtitle"]),
        Spacer(1, 1.3 * cm),
        Table(
            [
                ["Periodo", f"{report.start_date.isoformat()} a {report.end_date.isoformat()}"],
                ["Filtro horario", time_text],
                ["Perfiles encontrados", str(summary["requested_profiles"])],
                ["Versión del informe", REPORT_VERSION],
                ["Generado", timezone.localtime().strftime("%Y-%m-%d %H:%M UTC")],
            ],
            colWidths=(5.0 * cm, 9.5 * cm),
            style=_key_value_table_style(),
        ),
        Spacer(1, 2.0 * cm),
        Paragraph(
            "Resumen físico determinista calculado con los perfiles normalizados, "
            "MetPy y los diagnósticos del backend.",
            styles["CoverNote"],
        ),
    ]


def _executive_summary_story(report, summary, styles):
    distribution = summary["stability_distribution"]
    predominant = (
        max(distribution, key=distribution.get) if distribution else "No disponible"
    )
    paragraphs = [
        Paragraph("Resumen ejecutivo", styles["SectionTitle"]),
        Paragraph(
            f"Se encontraron {summary['requested_profiles']} perfiles entre "
            f"{report.start_date.isoformat()} y {report.end_date.isoformat()}. "
            f"{summary['successful_profiles']} se procesaron completamente, "
            f"{summary['partial_profiles']} tuvieron resultados parciales y "
            f"{summary['failed_profiles']} no pudieron normalizarse.",
            styles["Body"],
        ),
        Paragraph(
            f"La clasificación de estabilidad más frecuente fue: {predominant}.",
            styles["Body"],
        ),
        Spacer(1, 0.2 * cm),
        Paragraph("Indicadores agregados", styles["SubsectionTitle"]),
    ]
    metric_rows = [["Indicador", "Mínimo", "Promedio", "Máximo", "Disponibles"]]
    for label, key, unit in (
        ("Temperatura superficial", "surface_temperature_c", "°C"),
        ("Humedad superficial", "surface_relative_humidity_pct", "%"),
        ("SB CAPE", "sb_cape_j_kg", "J/kg"),
        ("ML CAPE 50 hPa", "ml_cape_j_kg", "J/kg"),
        ("Agua precipitable", "precipitable_water_mm", "mm"),
        ("Viento máximo", "maximum_wind_ms", "m/s"),
        ("Cizalladura 0-6 km", "bulk_shear_0_6km_ms", "m/s"),
    ):
        metric = summary["metrics"].get(key)
        if metric is None:
            metric_rows.append([label, "-", "-", "-", "0"])
        else:
            metric_rows.append(
                [
                    label,
                    f"{metric['minimum']:.2f} {unit}",
                    f"{metric['mean']:.2f} {unit}",
                    f"{metric['maximum']:.2f} {unit}",
                    str(metric["available_count"]),
                ]
            )
    paragraphs.append(
        Table(
            metric_rows,
            repeatRows=1,
            colWidths=(5.2 * cm, 2.9 * cm, 2.9 * cm, 2.9 * cm, 2.2 * cm),
            style=_data_table_style(),
        )
    )
    paragraphs.append(Spacer(1, 0.35 * cm))
    paragraphs.append(Paragraph("Distribución de estabilidad", styles["SubsectionTitle"]))
    stability_rows = [["Categoría", "Perfiles"]] + [
        [label, str(count)]
        for label, count in sorted(distribution.items(), key=lambda item: (-item[1], item[0]))
    ]
    paragraphs.append(
        Table(
            stability_rows,
            repeatRows=1,
            colWidths=(10.5 * cm, 3.5 * cm),
            style=_data_table_style(),
        )
    )
    return paragraphs


def _extremes_story(summary, styles):
    labels = {
        "surface_temperature_c": ("Temperatura superficial", "°C"),
        "ml_cape_j_kg": ("ML CAPE 50 hPa", "J/kg"),
        "maximum_wind_ms": ("Viento máximo", "m/s"),
        "bulk_shear_0_6km_ms": ("Cizalladura 0-6 km", "m/s"),
    }
    rows = [["Indicador", "Extremo", "Valor", "Fecha y hora", "Perfil"]]
    for key, values in summary["extremes"].items():
        label, unit = labels[key]
        for extreme_label, extreme_key in (("Máximo", "maximum"), ("Mínimo", "minimum")):
            item = values[extreme_key]
            rows.append(
                [
                    label,
                    extreme_label,
                    f"{item['value']:.2f} {unit}",
                    f"{item['date']} {item.get('time') or ''}".strip(),
                    str(item["profile_id"]),
                ]
            )
    return [
        KeepTogether(
            [
                Paragraph("Valores destacados", styles["SectionTitle"]),
                Table(
                    rows,
                    repeatRows=1,
                    colWidths=(4.5 * cm, 2.2 * cm, 3.2 * cm, 4.2 * cm, 1.5 * cm),
                    style=_data_table_style(),
                ),
            ]
        )
    ]


def _inventory_story(rows, styles):
    data = [["ID", "Fecha", "Hora", "Estado", "Estabilidad", "ML CAPE", "Viento máx."]]
    for row in rows:
        data.append(
            [
                str(row["profile_id"]),
                row["date"],
                row.get("time") or "-",
                {"ok": "Completo", "partial": "Parcial", "failed": "Fallido"}[row["status"]],
                row.get("stability_label") or "-",
                _format_value(row.get("ml_cape_j_kg"), "J/kg"),
                _format_value(row.get("maximum_wind_ms"), "m/s"),
            ]
        )
    return [
        Paragraph("Inventario de perfiles", styles["SectionTitle"]),
        Paragraph(
            "Un resultado parcial indica que el perfil fue normalizado, pero al menos "
            "un diagnóstico especializado no estuvo disponible.",
            styles["Body"],
        ),
        LongTable(
            data,
            repeatRows=1,
            colWidths=(1.3 * cm, 2.5 * cm, 1.7 * cm, 2.0 * cm, 4.2 * cm, 2.5 * cm, 2.7 * cm),
            style=_data_table_style(font_size=7.2),
        ),
    ]


def _methodology_story(styles):
    return [
        Paragraph("Metodología y limitaciones", styles["SectionTitle"]),
        Paragraph(
            "Cada TSV se descarga desde Cloudflare R2 y se normaliza de forma "
            "independiente. Los perfiles se procesan secuencialmente para limitar "
            "el uso de memoria. Los cálculos termodinámicos, de estabilidad y viento "
            "reutilizan los servicios MetPy del backend.",
            styles["Body"],
        ),
        Paragraph(
            "Los índices basados en 850 hPa no se utilizan porque ese nivel suele "
            "estar por debajo de la superficie de La Paz. Las categorías resumen "
            "un perfil por capas y no sustituyen el criterio meteorológico.",
            styles["Body"],
        ),
        Paragraph(
            "La primera versión incluye gráficos temporales y estadísticas agregadas. "
            "No incorpora automáticamente un Skew-T ni un hodógrafo por cada perfil.",
            styles["Body"],
        ),
    ]


def _render_temporal_chart(rows: list[dict]) -> BytesIO | None:
    usable = [row for row in rows if row["status"] != "failed"]
    if not usable:
        return None
    timestamps = [
        datetime.fromisoformat(
            f"{row['date']}T{(row.get('time') or '00:00Z').replace('Z', ':00')}"
        )
        for row in usable
    ]
    series = (
        ("Temperatura superficial", "surface_temperature_c", "°C", "#dc2626"),
        ("ML CAPE 50 hPa", "ml_cape_j_kg", "J/kg", "#7c3aed"),
        ("Viento máximo", "maximum_wind_ms", "m/s", "#0369a1"),
        ("Cizalladura 0-6 km", "bulk_shear_0_6km_ms", "m/s", "#047857"),
    )
    figure, axes = plt.subplots(2, 2, figsize=(11.2, 6.5), dpi=150)
    try:
        for axis, (title, key, unit, color) in zip(axes.flat, series):
            values = [row.get(key) for row in usable]
            valid = [index for index, value in enumerate(values) if _finite(value)]
            if len(valid) == 1:
                index = valid[0]
                axis.scatter(
                    [0],
                    [float(values[index])],
                    color=color,
                    s=22,
                )
                axis.set_xlim(-1, 1)
                axis.set_xticks([0])
                axis.set_xticklabels(
                    [timestamps[index].strftime("%d-%m-%Y\n%H:%MZ")],
                    fontsize=7.5,
                )
            elif valid:
                axis.plot(
                    [timestamps[index] for index in valid],
                    [float(values[index]) for index in valid],
                    color=color,
                    marker="o",
                    markersize=2.7,
                    linewidth=1.2,
                )
            else:
                axis.text(0.5, 0.5, "Sin datos disponibles", ha="center", va="center")
            axis.set_title(title, fontsize=10, fontweight="bold")
            axis.set_ylabel(unit)
            axis.grid(alpha=0.2)
            if len(valid) > 1:
                axis.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3, maxticks=6))
                axis.xaxis.set_major_formatter(mdates.DateFormatter("%d-%m"))
        figure.suptitle("Evolución de indicadores del intervalo", fontsize=13, fontweight="bold")
        figure.tight_layout(rect=(0, 0, 1, 0.96))
        chart = BytesIO()
        figure.savefig(chart, format="png", bbox_inches="tight", facecolor="white")
        chart.seek(0)
        return chart
    finally:
        plt.close(figure)


def _report_styles():
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="CoverTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=30,
            textColor=colors.HexColor("#0f172a"),
            alignment=TA_CENTER,
            spaceAfter=10,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CoverSubtitle",
            parent=styles["Heading2"],
            fontSize=15,
            leading=20,
            textColor=colors.HexColor("#334155"),
            alignment=TA_CENTER,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CoverNote",
            parent=styles["BodyText"],
            fontSize=10,
            leading=15,
            textColor=colors.HexColor("#475569"),
            alignment=TA_CENTER,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SectionTitle",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=19,
            textColor=colors.HexColor("#1e3a8a"),
            spaceBefore=8,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SubsectionTitle",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#334155"),
            spaceBefore=5,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Body",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9.3,
            leading=13.5,
            textColor=colors.HexColor("#1f2937"),
            alignment=TA_LEFT,
            spaceAfter=7,
        )
    )
    return styles


def _key_value_table_style():
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e2e8f0")),
            ("BACKGROUND", (1, 0), (1, -1), colors.HexColor("#f8fafc")),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#0f172a")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ]
    )


def _data_table_style(font_size=8.2):
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), font_size),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]
    )


def _draw_page_frame(canvas, document):
    canvas.saveState()
    width, height = A4
    canvas.setStrokeColor(colors.HexColor("#cbd5e1"))
    canvas.setLineWidth(0.5)
    canvas.line(1.55 * cm, height - 1.2 * cm, width - 1.55 * cm, height - 1.2 * cm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#64748b"))
    canvas.drawString(1.55 * cm, 0.85 * cm, "Sistema de radiosondeos - La Paz")
    canvas.drawRightString(width - 1.55 * cm, 0.85 * cm, f"Página {document.page}")
    canvas.restoreState()


def _store_pdf(report, object_key: str, pdf_bytes: bytes) -> None:
    try:
        get_r2_client().put_object(
            Bucket=report.bucket,
            Key=object_key,
            Body=pdf_bytes,
            ContentType="application/pdf",
            ContentDisposition=f'inline; filename="{report.filename}"',
            CacheControl="private, max-age=3600",
            Metadata={
                "report-id": str(report.pk),
                "report-version": REPORT_VERSION,
                "fingerprint": report.fingerprint,
            },
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "Unknown")
        raise RadiosondeReportError(
            f"R2 rechazó el guardado del informe: {code}."
        ) from exc
    except BotoCoreError as exc:
        raise RadiosondeReportError(
            "No se pudo conectar con R2 para guardar el informe."
        ) from exc


def _fingerprint(catalog, start_date, end_date, requested_time) -> str:
    payload = {
        "version": REPORT_VERSION,
        "render_revision": REPORT_RENDER_REVISION,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "time": requested_time.isoformat() if requested_time else None,
        "profiles": [
            {
                "id": item["id"],
                "date": item["date"].isoformat(),
                "time": item["time"].isoformat() if item["time"] else None,
                "bucket": item["bucket"],
                "object_key": item["object_key"],
            }
            for item in catalog
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _report_filename(start_date, end_date, requested_time):
    time_part = requested_time.strftime("-%H%MZ") if requested_time else ""
    return (
        f"informe-radiosondeos-LPZ-{start_date.isoformat()}_"
        f"{end_date.isoformat()}{time_part}.pdf"
    )


def _progress_percent(report):
    if report.status in (
        RadiosondeReport.Status.READY,
        RadiosondeReport.Status.FAILED,
    ):
        return 100
    if not report.profile_count:
        return 0
    return min(99, round(report.processed_count * 100 / report.profile_count))


def _extreme_payload(row, key):
    return {
        "profile_id": row["profile_id"],
        "date": row["date"],
        "time": row.get("time"),
        "value": round(float(row[key]), 2),
    }


def _format_value(value, unit):
    return "-" if not _finite(value) else f"{float(value):.1f} {unit}"


def _finite(value):
    try:
        return value is not None and bool(np.isfinite(float(value)))
    except (TypeError, ValueError):
        return False
