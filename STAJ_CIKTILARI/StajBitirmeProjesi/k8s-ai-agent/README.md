# k8s-ai-agent

Kubernetes cluster'larındaki sorunlu podları (CrashLoopBackOff, OOMKilled,
ImagePullBackOff, Error) otomatik tespit eden, hassas veriyi maskeleyen ve
Google Gemini ile kök neden analizi yapan bir DevOps aracı.

## Kurulum

```bash
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`.env` dosyasına Gemini API key'ini ekle: