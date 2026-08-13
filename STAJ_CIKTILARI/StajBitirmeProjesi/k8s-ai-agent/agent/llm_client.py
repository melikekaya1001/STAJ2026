"""
llm_client.py
Aşama 3: Yapay Zeka (LLM) Entegrasyonu

Bu modül, maskelenmiş pod verisini (events + previous_logs) Gemini'ye
gönderir ve yapılandırılmış (JSON) bir teşhis sonucu alır.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from dotenv import load_dotenv
from google import genai
from google.genai import types

# .env dosyasındaki GEMINI_API_KEY'i ortam değişkeni olarak yükler
load_dotenv()

MODEL_NAME = "gemini-3.5-flash"

SYSTEM_INSTRUCTION = """\
Sen uzman bir Kubernetes hata ayıklayıcısısın (SRE / DevOps uzmanı).
Sana bir podun durumu (reason), olay (event) geçmişi ve önceki loglarını vereceğim.
Bu bilgilere dayanarak sorunun kök nedenini tespit et ve çözüm öner.

Yanıtını SADECE aşağıdaki JSON formatında ver. Başka hiçbir açıklama, markdown
işareti veya kod bloğu (```) ekleme, doğrudan geçerli JSON döndür:

{
  "root_cause": "kısa ve net kök neden (1-2 cümle)",
  "confidence": "high" | "medium" | "low",
  "error_category": "OOMKilled" | "ImagePullBackOff" | "CrashLoopBackOff" | "LivenessProbeFailure" | "Other",
  "explanation": "detaylı açıklama, 1 paragraf",
  "suggested_actions": [
    {"command": "kubectl ... komutu", "reason": "bu komut neden öneriliyor"}
  ]
}

suggested_actions listesinde tam olarak 3 madde olsun.
"""


@dataclass
class SuggestedAction:
    command: str
    reason: str


@dataclass
class DiagnosisResult:
    root_cause: str
    confidence: str
    error_category: str
    explanation: str
    suggested_actions: list[SuggestedAction]
    raw_response: str = ""  # parse başarısız olursa ham metni burada tutarız


def _build_user_prompt(reason: str, masked_events: list[str], masked_previous_logs: str) -> str:
    events_text = "\n".join(masked_events) if masked_events else "(event bulunamadi)"
    logs_text = masked_previous_logs if masked_previous_logs else "(onceki log bulunamadi)"

    return f"""\
Pod Durumu (reason): {reason}

--- Events ---
{events_text}

--- Onceki Loglar (previous logs) ---
{logs_text}
"""


def diagnose_pod(reason: str, masked_events: list[str], masked_previous_logs: str) -> DiagnosisResult:
    """
    Maskelenmiş pod verisini Gemini'ye gönderir ve yapılandırılmış
    bir DiagnosisResult döndürür. LLM formatı bozarsa (geçersiz JSON
    dönerse) hata fırlatmak yerine ham metni raw_response'a koyup
    diğer alanları "Bilinmiyor" ile doldurur; program çökmez.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY bulunamadi. .env dosyasini kontrol et."
        )

    client = genai.Client(api_key=api_key)
    user_prompt = _build_user_prompt(reason, masked_events, masked_previous_logs)

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
           
        ),
    )

    raw_text = response.text.strip()

    # LLM bazen JSON'u ```json ... ``` bloğu içine koyabiliyor, temizleyelim
    cleaned = raw_text
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[len("json"):]
    cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
        actions = [
            SuggestedAction(command=a["command"], reason=a["reason"])
            for a in data.get("suggested_actions", [])
        ]
        return DiagnosisResult(
            root_cause=data.get("root_cause", "Bilinmiyor"),
            confidence=data.get("confidence", "low"),
            error_category=data.get("error_category", "Other"),
            explanation=data.get("explanation", ""),
            suggested_actions=actions,
            raw_response=raw_text,
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        # Parse basarisiz olursa programi cokertme, ham cevabi goster
        return DiagnosisResult(
            root_cause="LLM yaniti parse edilemedi",
            confidence="low",
            error_category="Other",
            explanation="Ham yanit asagida gosteriliyor.",
            suggested_actions=[],
            raw_response=raw_text,
        )


if __name__ == "__main__":
    # Hizli manuel test
    result = diagnose_pod(
        reason="CrashLoopBackOff",
        masked_events=[
            "Warning/BackOff: Back-off restarting failed container broken-container"
        ],
        masked_previous_logs="Baslatildi...\nkontrollu cokme\n",
    )

    print("Root cause:", result.root_cause)
    print("Confidence:", result.confidence)
    print("Category:", result.error_category)
    print("Explanation:", result.explanation)
    print("Suggested actions:")
    for a in result.suggested_actions:
        print(" -", a.command, "|", a.reason)