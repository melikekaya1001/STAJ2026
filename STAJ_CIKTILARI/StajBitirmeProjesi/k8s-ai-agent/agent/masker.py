"""
masker.py
Aşama 2: Hassas Veri Maskeleme

Bu modül, LLM'e gönderilecek log/event metinlerini tarar ve
içindeki potansiyel hassas verileri (IP adresi, şifre, API key, token vb.)
regex ile bulup yerine [MASKED_...] etiketleri koyar.
"""

from __future__ import annotations

import re

# Her pattern bir isim ile eşleşiyor, bu sayede hangi kuralın
# kaç eşleşme bulduğunu raporlayabiliyoruz.
PATTERNS: dict[str, re.Pattern] = {
    # IPv4 adresi: 192.168.1.10 gibi
    "IP": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),

    # key=value formatındaki şifre/secret/token alanları
    # Örnek: password=abc123  api_key: "xyz"  secret='qwe'
    "SECRET_KV": re.compile(
        r"(?i)\b(password|passwd|pwd|api[_-]?key|secret|token)\b\s*[:=]\s*['\"]?[^\s'\"]+['\"]?"
    ),

    # Authorization: Bearer <token>
    "BEARER_TOKEN": re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-_.=]+"),

    # Kubernetes secret'larında sık görülen base64 benzeri uzun stringler
    # (en az 20 karakter, sadece base64 alfabesinden oluşan)
    "POSSIBLE_BASE64_SECRET": re.compile(r"\b[A-Za-z0-9+/]{20,}={0,2}\b"),
}

MASK_LABELS: dict[str, str] = {
    "IP": "[MASKED_IP]",
    "SECRET_KV": "[MASKED_SECRET]",
    "BEARER_TOKEN": "[MASKED_TOKEN]",
    "POSSIBLE_BASE64_SECRET": "[MASKED_BASE64]",
}


def mask_text(text: str) -> tuple[str, dict[str, int]]:
    """
    Verilen metin içindeki hassas verileri maskeler.

    Dönüş:
      - maskelenmiş metin
      - her pattern için kaç eşleşme bulunduğunu gösteren bir sözlük
        (örn. {"IP": 2, "SECRET_KV": 1, "BEARER_TOKEN": 0, "POSSIBLE_BASE64_SECRET": 0})
    """
    if not text:
        return text, {name: 0 for name in PATTERNS}

    counts: dict[str, int] = {}
    masked = text

    # Sıra önemli: önce daha "spesifik" pattern'ler (SECRET_KV, BEARER_TOKEN),
    # en son daha "genel" olan POSSIBLE_BASE64_SECRET çalışsın.
    # Böylece bir token zaten SECRET_KV tarafından maskelenmişse,
    # base64 pattern'i onun üstüne tekrar maskeleme uygulamaz.
    order = ["SECRET_KV", "BEARER_TOKEN", "IP", "POSSIBLE_BASE64_SECRET"]

    for name in order:
        pattern = PATTERNS[name]
        label = MASK_LABELS[name]
        matches = pattern.findall(masked)
        counts[name] = len(matches)
        masked = pattern.sub(label, masked)

    return masked, counts


def mask_problem_pod_data(events: list[str], previous_logs: str, current_logs: str):
    """
    ProblemPod'dan gelen ham veriyi (events listesi + iki log alanı) maskeler.
    LLM'e gönderilecek olan budur; ham veri asla LLM'e gitmemeli.
    """
    masked_events = []
    total_counts: dict[str, int] = {}

    for ev in events:
        masked_ev, counts = mask_text(ev)
        masked_events.append(masked_ev)
        for k, v in counts.items():
            total_counts[k] = total_counts.get(k, 0) + v

    masked_previous, counts_prev = mask_text(previous_logs)
    for k, v in counts_prev.items():
        total_counts[k] = total_counts.get(k, 0) + v

    masked_current, counts_curr = mask_text(current_logs)
    for k, v in counts_curr.items():
        total_counts[k] = total_counts.get(k, 0) + v

    return masked_events, masked_previous, masked_current, total_counts


if __name__ == "__main__":
    # Hızlı manuel test: python masker.py
    sample = """
    2026-08-11T09:00:00Z ERROR failed to connect to database at 192.168.1.55
    Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc123
    Config loaded: password=SuperGizli123 api_key: "sk-test-9f8e7d6c5b4a"
    Connection retry from node 10.0.0.12
    """

    masked, counts = mask_text(sample)
    print("--- Orijinal ---")
    print(sample)
    print("--- Maskelenmis ---")
    print(masked)
    print("--- Eslesme sayilari ---")
    print(counts)