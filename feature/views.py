from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from drf_spectacular.utils import extend_schema
from .models import RadiosondeProfile
from .serializers import (
    RadiosondeSearchQuerySerializer,
    RadiosondeSearchResponseSerializer,
    RadiosondeSearchResultSerializer,
    RadiosondeUploadSerializer,
)

from .rs_core import process_uploaded_tsv
from .llm_groq import summarize_radiosonde

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
