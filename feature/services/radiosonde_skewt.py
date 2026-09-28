from dataclasses import dataclass
import hashlib
from io import BytesIO
import math

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from metpy.plots import SkewT
from metpy.units import units
import numpy as np
from botocore.exceptions import BotoCoreError, ClientError

from .r2_client import get_r2_client
from .radiosonde_normalizer import NormalizedRadiosonde, normalize_radiosonde
from .radiosonde_thermodynamics import (
    ThermodynamicAnalysis,
    calculate_thermodynamics,
)


PLOT_VERSION = "v4"
MAX_SKEWT_BYTES = 5 * 1024 * 1024


class RadiosondeSkewTError(Exception):
    """Error controlado al generar, guardar o recuperar un Skew-T."""


@dataclass
class SkewTArtifact:
    profile_id: int
    bucket: str
    object_key: str
    source_sha256: str
    filename: str
    size_bytes: int
    cached: bool
    diagnostics: dict | None = None
    png_bytes: bytes | None = None

    def descriptor(self, normalized: NormalizedRadiosonde) -> dict:
        profile = normalized.general_response()["profile"]
        public_path = f"/api/radiosondes/{self.profile_id}/skew-t/image"
        return {
            "type": "skew_t_diagram",
            "profile": profile,
            "image_path": public_path,
            "download_path": f"{public_path}?download=true",
            "filename": self.filename,
            "content_type": "image/png",
            "size_bytes": self.size_bytes,
            "plot_version": PLOT_VERSION,
            "source_sha256": self.source_sha256,
            "cached": self.cached,
            "diagnostics": self.diagnostics or calculate_skewt_diagnostics(normalized),
            "summary": (
                "Skew-T completo con temperatura, punto de rocío, parcela "
                "superficial, SB/ML/MU CAPE-CIN, niveles característicos, "
                "índices termodinámicos y viento."
            ),
        }


def get_or_create_skewt(profile_id: int) -> tuple[SkewTArtifact, NormalizedRadiosonde]:
    """Normaliza el perfil y garantiza que su PNG derivado exista en R2."""
    normalized = normalize_radiosonde(profile_id)
    source_hash = hashlib.sha256(normalized.source.raw_bytes).hexdigest()
    object_key = (
        f"derived/skew-t/{PLOT_VERSION}/profile-{profile_id}/{source_hash}.png"
    )
    filename = _filename(normalized)
    bucket = normalized.source.record.bucket
    client = get_r2_client()
    thermodynamics = calculate_thermodynamics(normalized)
    diagnostics = thermodynamics.diagram_diagnostics()

    cached_size = _cached_size(client, bucket, object_key)
    if cached_size is not None:
        return (
            SkewTArtifact(
                profile_id=profile_id,
                bucket=bucket,
                object_key=object_key,
                source_sha256=source_hash,
                filename=filename,
                size_bytes=cached_size,
                cached=True,
                diagnostics=diagnostics,
            ),
            normalized,
        )

    png_bytes = render_skewt_png(
        normalized,
        diagnostics=diagnostics,
        thermodynamics=thermodynamics,
    )
    if len(png_bytes) > MAX_SKEWT_BYTES:
        raise RadiosondeSkewTError(
            f"El PNG generado supera el límite de {MAX_SKEWT_BYTES} bytes."
        )

    try:
        client.put_object(
            Bucket=bucket,
            Key=object_key,
            Body=png_bytes,
            ContentType="image/png",
            CacheControl="private, max-age=3600",
            Metadata={
                "profile-id": str(profile_id),
                "source-sha256": source_hash,
                "plot-version": PLOT_VERSION,
            },
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "Unknown")
        raise RadiosondeSkewTError(
            f"R2 rechazó el guardado del Skew-T: {code}."
        ) from exc
    except BotoCoreError as exc:
        raise RadiosondeSkewTError(
            "No se pudo conectar con R2 para guardar el Skew-T."
        ) from exc

    return (
        SkewTArtifact(
            profile_id=profile_id,
            bucket=bucket,
            object_key=object_key,
            source_sha256=source_hash,
            filename=filename,
            size_bytes=len(png_bytes),
            cached=False,
            diagnostics=diagnostics,
            png_bytes=png_bytes,
        ),
        normalized,
    )


def load_skewt_png(profile_id: int) -> tuple[SkewTArtifact, bytes]:
    """Devuelve el PNG cacheado, generándolo primero cuando sea necesario."""
    artifact, _ = get_or_create_skewt(profile_id)
    if artifact.png_bytes is not None:
        return artifact, artifact.png_bytes

    client = get_r2_client()
    try:
        response = client.get_object(
            Bucket=artifact.bucket,
            Key=artifact.object_key,
        )
    except (ClientError, BotoCoreError) as exc:
        raise RadiosondeSkewTError(
            "No se pudo recuperar el Skew-T almacenado en R2."
        ) from exc

    body = response["Body"]
    try:
        png_bytes = body.read(MAX_SKEWT_BYTES + 1)
    finally:
        body.close()
    if len(png_bytes) > MAX_SKEWT_BYTES:
        raise RadiosondeSkewTError(
            f"El PNG supera el límite de {MAX_SKEWT_BYTES} bytes."
        )
    return artifact, png_bytes


def calculate_skewt_diagnostics(normalized: NormalizedRadiosonde) -> dict:
    """Adapta el motor común al contrato compacto del diagrama."""
    return calculate_thermodynamics(normalized).diagram_diagnostics()


def render_skewt_png(
    normalized: NormalizedRadiosonde,
    diagnostics: dict | None = None,
    thermodynamics: ThermodynamicAnalysis | None = None,
) -> bytes:
    """Renderiza un Skew-T PNG íntegramente en memoria."""
    thermodynamics = thermodynamics or calculate_thermodynamics(normalized)
    dataframe = normalized.dataframe
    pressure = thermodynamics.pressure
    temperature = thermodynamics.temperature
    dewpoint = thermodynamics.dewpoint
    temperature_c = temperature.to("degC")
    dewpoint_c = dewpoint.to("degC")
    parcel = thermodynamics.surface_parcel.to("degC")
    diagnostics = diagnostics or thermodynamics.diagram_diagnostics()

    figure = plt.figure(figsize=(13, 10), dpi=140)
    try:
        layout = figure.add_gridspec(
            1,
            2,
            width_ratios=(4.25, 1.35),
            wspace=0.24,
        )
        skew = SkewT(figure, rotation=30, subplot=layout[0])
        diagnostics_axis = figure.add_subplot(layout[1])
        skew.plot(pressure, temperature_c, color="#dc2626", linewidth=2.2, label="Temperatura")
        skew.plot(pressure, dewpoint_c, color="#15803d", linewidth=2.0, label="Punto de rocío")
        skew.plot(pressure, parcel, color="#111827", linewidth=1.5, label="Parcela superficial")

        skew.plot_dry_adiabats(alpha=0.18, color="#b45309")
        skew.plot_moist_adiabats(alpha=0.18, color="#0f766e")
        skew.plot_mixing_lines(alpha=0.18, color="#2563eb", linestyle="dotted")

        try:
            skew.shade_cape(pressure, temperature_c, parcel, alpha=0.22, color="#ef4444")
            skew.shade_cin(
                pressure,
                temperature_c,
                parcel,
                dewpoint_c,
                alpha=0.18,
                color="#2563eb",
            )
        except (ValueError, IndexError):
            pass

        _plot_characteristic_levels(skew, thermodynamics.level_markers)
        _plot_wind_barbs(skew, dataframe, pressure)
        _configure_axes(skew, pressure, temperature_c, dewpoint_c)
        _plot_diagnostics_panel(diagnostics_axis, diagnostics)

        profile = normalized.general_response()["profile"]
        station = profile.get("station") or "La Paz"
        valid_time = profile.get("observed_at") or (
            f"{profile['date']} {profile.get('time') or ''}".strip()
        )
        skew.ax.set_title(f"Skew-T — {station}", loc="left", fontsize=12, weight="bold")
        skew.ax.set_title(valid_time, loc="right", fontsize=10)
        skew.ax.set_xlabel("Temperatura (°C)")
        skew.ax.set_ylabel("Presión (hPa)")
        skew.ax.legend(loc="best", fontsize=9)
        skew.ax.grid(True, which="major", alpha=0.16)

        buffer = BytesIO()
        figure.savefig(
            buffer,
            format="png",
            bbox_inches="tight",
            facecolor="white",
            metadata={"Software": f"MetPy {PLOT_VERSION}"},
        )
        return buffer.getvalue()
    except Exception as exc:
        raise RadiosondeSkewTError(f"No se pudo renderizar el Skew-T: {exc}") from exc
    finally:
        plt.close(figure)


def _plot_diagnostics_panel(axis, diagnostics):
    axis.set_axis_off()
    axis.set_facecolor("#f8fafc")
    axis.set_xlim(0.0, 1.0)
    axis.set_ylim(0.0, 1.0)

    axis.text(
        0.04,
        0.97,
        "DIAGNÓSTICO",
        fontsize=12,
        fontweight="bold",
        color="#0f172a",
        va="top",
    )
    y = 0.91
    y = _panel_section(axis, y, "ENERGÍA DE PARCELA")
    for label, key in (
        ("SB", "surface_based"),
        ("ML 50 hPa", "mixed_layer_50hpa"),
        ("MU 300 hPa", "most_unstable_300hpa"),
    ):
        values = diagnostics[key]
        y = _panel_value(
            axis,
            y,
            f"{label} CAPE",
            values["cape_j_kg"],
            "J/kg",
            "#b91c1c",
        )
        y = _panel_value(
            axis,
            y,
            f"{label} CIN",
            values["cin_j_kg"],
            "J/kg",
            "#1d4ed8",
        )
        y -= 0.008

    y = _panel_section(axis, y, "NIVELES")
    levels = diagnostics["levels"]
    for label, key in (
        ("LCL", "lcl_pressure_hpa"),
        ("LFC", "lfc_pressure_hpa"),
        ("EL", "el_pressure_hpa"),
        ("CCL", "ccl_pressure_hpa"),
    ):
        y = _panel_value(axis, y, label, levels[key], "hPa")

    y = _panel_section(axis, y - 0.008, "ÍNDICES")
    indices = diagnostics["indices"]
    y = _panel_value(axis, y, "Lifted Index", indices["lifted_index_c"], "°C")
    y = _panel_value(
        axis,
        y,
        "Agua precipitable",
        indices["precipitable_water_mm"],
        "mm",
    )
    _panel_value(
        axis,
        y,
        "Temp. convectiva",
        indices["convective_temperature_c"],
        "°C",
    )

    axis.text(
        0.04,
        0.025,
        "Rojo: CAPE  ·  Azul: CIN\n—: no calculable con este perfil",
        fontsize=7.5,
        color="#475569",
        va="bottom",
    )


def _panel_section(axis, y, title):
    axis.text(
        0.04,
        y,
        title,
        fontsize=8.5,
        fontweight="bold",
        color="#334155",
        va="top",
    )
    return y - 0.042


def _panel_value(axis, y, label, value, unit, color="#0f172a"):
    formatted = "—" if value is None else f"{value:.1f} {unit}"
    axis.text(
        0.04,
        y,
        f"{label}: {formatted}",
        fontsize=7.8,
        fontweight="bold",
        color=color,
        va="top",
    )
    return y - 0.034


def _cached_size(client, bucket: str, object_key: str) -> int | None:
    try:
        response = client.head_object(Bucket=bucket, Key=object_key)
        return int(response.get("ContentLength") or 0)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        status_code = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in {"404", "NoSuchKey", "NotFound"} or status_code == 404:
            return None
        raise RadiosondeSkewTError(
            f"R2 rechazó la consulta de caché del Skew-T: {code or 'Unknown'}."
        ) from exc
    except BotoCoreError as exc:
        raise RadiosondeSkewTError(
            "No se pudo consultar la caché del Skew-T en R2."
        ) from exc


def _plot_characteristic_levels(skew, level_markers):
    colors = {"LCL": "#06b6d4", "LFC": "#d946ef", "EL": "#f97316"}
    for label, (level_pressure, level_temperature) in level_markers.items():
        if _finite_quantity(level_pressure) and _finite_quantity(level_temperature):
            skew.ax.plot(
                level_temperature.to("degC"),
                level_pressure,
                marker="o",
                markersize=6,
                markerfacecolor=colors[label],
                markeredgecolor="#111827",
                linestyle="none",
                label=label,
            )


def _plot_wind_barbs(skew, dataframe, pressure):
    if "u_wind_ms" not in dataframe or "v_wind_ms" not in dataframe:
        return
    u = dataframe["u_wind_ms"].to_numpy(dtype=float)
    v = dataframe["v_wind_ms"].to_numpy(dtype=float)
    valid = np.isfinite(u) & np.isfinite(v)
    if not valid.any():
        return
    valid_indices = np.flatnonzero(valid)
    selected = valid_indices[
        np.unique(np.linspace(0, len(valid_indices) - 1, min(28, len(valid_indices))).astype(int))
    ]
    skew.plot_barbs(
        pressure[selected],
        u[selected] * units("m/s"),
        v[selected] * units("m/s"),
        xloc=1.015,
        length=5,
        linewidth=0.6,
    )


def _configure_axes(skew, pressure, temperature, dewpoint):
    surface_pressure = float(pressure[0].to("hPa").magnitude)
    top_pressure = float(pressure[-1].to("hPa").magnitude)
    pressure_bottom = min(1050.0, math.ceil(surface_pressure / 50.0) * 50.0)
    pressure_top = max(30.0, math.floor(top_pressure / 10.0) * 10.0)
    skew.ax.set_ylim(pressure_bottom, pressure_top)

    temperature_values = np.concatenate(
        [temperature.magnitude, dewpoint.magnitude]
    )
    finite = temperature_values[np.isfinite(temperature_values)]
    lower = math.floor((float(finite.min()) - 5.0) / 10.0) * 10.0
    upper = math.ceil((float(finite.max()) + 8.0) / 10.0) * 10.0
    skew.ax.set_xlim(max(-120.0, lower), min(60.0, upper))


def _filename(normalized: NormalizedRadiosonde) -> str:
    record = normalized.source.record
    time_part = record.time.strftime("%H%MZ") if record.time else "sin-hora"
    return f"skew-t-LPZ-{record.date.isoformat()}-{time_part}.png"


def _finite_quantity(value) -> bool:
    try:
        return bool(np.isfinite(np.asarray(value.magnitude, dtype=float)).all())
    except (AttributeError, TypeError, ValueError):
        return False
