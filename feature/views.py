from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework import status

from .rs_core import process_uploaded_tsv
from .llm_groq import summarize_radiosonde

from io import BytesIO

class RadiosondeProcessView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, *args, **kwargs):
        # 1) Obtener archivo (multipart o raw)
        up = request.FILES.get('file') or request.FILES.get('upload')
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
