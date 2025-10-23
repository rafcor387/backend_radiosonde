import os
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

_MODEL_DEFAULT = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

def _make_client():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("Falta GROQ_API_KEY en variables de entorno / .env")
    return Groq(api_key=api_key)

def _compact_levels(levels, keep=12):
    """
    Reduce el tamaño del payload: toma <=keep niveles, muestreados del perfil,
    y solo con campos clave.
    """
    if not levels:
        return []

    # fields clave para el LLM (puedes ajustar)
    cols = ["p_hPa","z_m","T_K","Td_K","RH_0_1","theta_K","Gamma_env_Kkm"]
    L = len(levels)
    if L <= keep:
        return [{k: round(l[k], 4) for k in cols if k in l} for l in levels]

    # muestreamos índices aproximadamente uniformes
    import numpy as np
    idx = np.linspace(0, L-1, keep).astype(int).tolist()
    sampled = [levels[i] for i in idx]
    return [{k: round(l[k], 4) for k in cols if k in l} for l in sampled]

def summarize_radiosonde(record: dict, language: str = "es", model_id: str = None) -> str:
    """
    Usa Groq LLM para generar una descripción/summary del radiosondeo procesado.
    - record: dict con keys: file, date, label, summary{...}, levels[...]
    - language: 'es' o 'en'
    - model_id: override del modelo (opcional)
    """
    client = _make_client()
    model = model_id or _MODEL_DEFAULT

    # Reducimos niveles para no enviar payload gigante al LLM
    levels_small = _compact_levels(record.get("levels", []), keep=12)

    # Construimos un contexto compacto (JSON estilizado)
    compact = {
        "file": record.get("file"),
        "date": record.get("date"),
        "label": record.get("label"),
        "summary": record.get("summary", {}),
        "levels_sampled": levels_small
    }
    compact_json = json.dumps(compact, ensure_ascii=False, indent=2)

    system_msg = (
        "Eres un meteorólogo experto. Redacta en lenguaje claro, preciso y conciso. "
        "No inventes datos. Si algo falta, dilo explícitamente."
        if language.startswith("es") else
        "You are an expert meteorologist. Write clearly, precisely, and concisely. "
        "Do not hallucinate; if something is missing, say so."
    )

    user_instruction = (
        "Toma el siguiente perfil de radiosondeo ya procesado (con etiqueta física) y produce: "
        "1) Un resumen ejecutivo de 3–5 oraciones, "
        "2) Señales de inestabilidad o estabilidad y su justificación, "
        "3) Riesgos o implicancias operativas breves, "
        "4) Una breve explicación de la etiqueta asignada.\n\n"
        "Datos (JSON):\n"
        f"{compact_json}"
        if language.startswith("es") else
        "Given the processed radiosonde profile (with a physics-based label), produce: "
        "1) A 3–5 sentence executive summary, "
        "2) Instability/stability signals and rationale, "
        "3) Brief operational implications, "
        "4) A brief explanation of the assigned label.\n\n"
        "Data (JSON):\n"
        f"{compact_json}"
    )

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_instruction},
        ],
        temperature=0.3,   # más estable
        # max_tokens=800,  # ajusta si hace falta
    )
    return resp.choices[0].message.content.strip()
