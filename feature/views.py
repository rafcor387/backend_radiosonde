from rest_framework.views import APIView
from django.http import HttpResponse
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from drf_spectacular.utils import extend_schema, OpenApiTypes
from .models import RadiosondeProfile
from .serializers import (
    RadiosondeSearchQuerySerializer,
    RadiosondeSearchResponseSerializer,
    RadiosondeSearchResultSerializer,
    RadiosondeUploadSerializer,
)

from .rs_core import process_uploaded_tsv
from .llm_groq import summarize_radiosonde
from .services.radiosonde_normalizer import (
    RadiosondeNormalizationError,
    normalize_radiosonde,
)
from .services.radiosonde_source import RadiosondeSourceError
from .services.radiosonde_stability import (
    RadiosondeStabilityError,
    classify_radiosonde_stability,
)
from .services.radiosonde_skewt import (
    PLOT_VERSION as SKEWT_PLOT_VERSION,
    RadiosondeSkewTError,
    get_or_create_skewt,
    load_skewt_png,
)
from .services.radiosonde_hodograph import (
    PLOT_VERSION as HODOGRAPH_PLOT_VERSION,
    RadiosondeHodographError,
    get_or_create_hodograph,
    load_hodograph_png,
)

from io import BytesIO


class RadiosondeSearchView(APIView):
    """Busca los perfiles disponibles para una fecha, sin descargar el TSV."""

    # Primera versión: búsqueda pública de metadatos mínimos. No expone bucket,
    # object_key ni contenido del radiosondeo.
    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[RadiosondeSearchQuerySerializer],
        responses={200: RadiosondeSearchResponseSerializer},
    )
    def get(self, request, *args, **kwargs):
        query = RadiosondeSearchQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)

        profiles = RadiosondeProfile.objects.filter(
            date=query.validated_data["date"]
        ).order_by("time", "observed_at", "id")

        radiosondes = RadiosondeSearchResultSerializer(profiles, many=True).data
        return Response(
            {
                "count": len(radiosondes),
                "radiosondes": radiosondes,
            },
            status=status.HTTP_200_OK,
        )


class RadiosondeProfileView(APIView):
    """Devuelve los datos generales de un perfil normalizado en memoria."""

    permission_classes = [AllowAny]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request, profile_id, *args, **kwargs):
        if not RadiosondeProfile.objects.filter(pk=profile_id).exists():
            return Response(
                {"detail": f"No existe un radiosondeo con profile_id={profile_id}."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            result = normalize_radiosonde(profile_id).general_response()
        except RadiosondeSourceError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except RadiosondeNormalizationError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        return Response(result, status=status.HTTP_200_OK)


class RadiosondeStabilityView(APIView):
    """Clasifica la estabilidad física de un perfil normalizado."""

    permission_classes = [AllowAny]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request, profile_id, *args, **kwargs):
        if not RadiosondeProfile.objects.filter(pk=profile_id).exists():
            return Response(
                {"detail": f"No existe un radiosondeo con profile_id={profile_id}."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            result = classify_radiosonde_stability(profile_id)
        except RadiosondeSourceError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except (RadiosondeNormalizationError, RadiosondeStabilityError) as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        return Response(result, status=status.HTTP_200_OK)


class RadiosondeSkewTView(APIView):
    """Genera/cachea el Skew-T y devuelve sólo su descriptor público."""

    permission_classes = [AllowAny]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request, profile_id, *args, **kwargs):
        if not RadiosondeProfile.objects.filter(pk=profile_id).exists():
            return Response(
                {"detail": f"No existe un radiosondeo con profile_id={profile_id}."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            artifact, normalized = get_or_create_skewt(profile_id)
        except RadiosondeSourceError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except (RadiosondeNormalizationError, RadiosondeSkewTError) as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        return Response(
            artifact.descriptor(normalized),
            status=status.HTTP_200_OK,
        )


class RadiosondeSkewTImageView(APIView):
    """Entrega el PNG del Skew-T en línea o como descarga."""

    permission_classes = [AllowAny]

    @extend_schema(responses={(200, "image/png"): OpenApiTypes.BINARY})
    def get(self, request, profile_id, *args, **kwargs):
        if not RadiosondeProfile.objects.filter(pk=profile_id).exists():
            return Response(
                {"detail": f"No existe un radiosondeo con profile_id={profile_id}."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            artifact, png_bytes = load_skewt_png(profile_id)
        except RadiosondeSourceError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except (RadiosondeNormalizationError, RadiosondeSkewTError) as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        download = request.query_params.get("download", "false").lower() in {
            "1",
            "true",
            "yes",
        }
        disposition = "attachment" if download else "inline"
        response = HttpResponse(png_bytes, content_type="image/png")
        response["Content-Disposition"] = (
            f'{disposition}; filename="{artifact.filename}"'
        )
        response["Cache-Control"] = "private, max-age=3600"
        response["ETag"] = (
            f'"skew-t-{SKEWT_PLOT_VERSION}-{artifact.source_sha256}"'
        )
        return response


class RadiosondeHodographView(APIView):
    """Genera/cachea el hodógrafo y devuelve sólo su descriptor público."""

    permission_classes = [AllowAny]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request, profile_id, *args, **kwargs):
        if not RadiosondeProfile.objects.filter(pk=profile_id).exists():
            return Response(
                {"detail": f"No existe un radiosondeo con profile_id={profile_id}."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            artifact, normalized = get_or_create_hodograph(profile_id)
        except RadiosondeSourceError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except (RadiosondeNormalizationError, RadiosondeHodographError) as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        return Response(
            artifact.descriptor(normalized),
            status=status.HTTP_200_OK,
        )


class RadiosondeHodographImageView(APIView):
    """Entrega el PNG del hodógrafo en línea o como descarga."""

    permission_classes = [AllowAny]

    @extend_schema(responses={(200, "image/png"): OpenApiTypes.BINARY})
    def get(self, request, profile_id, *args, **kwargs):
        if not RadiosondeProfile.objects.filter(pk=profile_id).exists():
            return Response(
                {"detail": f"No existe un radiosondeo con profile_id={profile_id}."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            artifact, png_bytes = load_hodograph_png(profile_id)
        except RadiosondeSourceError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except (RadiosondeNormalizationError, RadiosondeHodographError) as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        download = request.query_params.get("download", "false").lower() in {
            "1",
            "true",
            "yes",
        }
        disposition = "attachment" if download else "inline"
        response = HttpResponse(png_bytes, content_type="image/png")
        response["Content-Disposition"] = (
            f'{disposition}; filename="{artifact.filename}"'
        )
        response["Cache-Control"] = "private, max-age=3600"
        response["ETag"] = (
            f'"hodograph-{HODOGRAPH_PLOT_VERSION}-{artifact.source_sha256}"'
        )
        return response

class RadiosondeProcessView(APIView):
    serializer_class = RadiosondeUploadSerializer
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, *args, **kwargs):
        #Pasamos los datos (incluyendo el archivo) al serializer
        serializer = self.serializer_class(data=request.data)
        
        #Validamos: ¿Es un archivo real? ¿Viene en el campo 'file'?
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        #Obtenemos el archivo ya validado de forma segura
        up = serializer.validated_data['file']

        if up is None and request.content_type and 'octet-stream' in request.content_type:
            up = BytesIO(request.body)
            up.name = request.headers.get('X-Filename', 'radiosonde.tsv')

        if up is None:
            diag = {
                "detail": "Falta archivo 'file'. Envía multipart/form-data con key 'file' o binary con Content-Type: application/octet-stream.",
                "content_type": request.content_type,
                "FILES_keys": list(request.FILES.keys()),
                "DATA_keys": list(request.data.keys()),
                "body_len": len(request.body) if hasattr(request, "body") else None,
            }
            return Response(diag, status=status.HTTP_400_BAD_REQUEST)

        filename = getattr(up, 'name', 'radiosonde.tsv')
        try:
            # 2) Procesar TSV -> JSON con métricas + etiqueta
            result = process_uploaded_tsv(up, filename=filename)

            # 3) ¿Generar resumen con LLM?
            summarize = request.query_params.get("summarize", "true").lower() != "false"
            lang = request.query_params.get("lang", "es")
            model_id = request.query_params.get("model")  # opcional

            if summarize:
                try:
                    narrative = summarize_radiosonde(result, language=lang, model_id=model_id)
                except Exception as e:
                    # No bloquear si el LLM falla; devolvemos datos igualmente
                    narrative = f"(No se pudo generar resumen LLM: {e})"
                result["narrative"] = narrative

            return Response(result, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"detail": f"Error procesando: {e}"}, status=500)
