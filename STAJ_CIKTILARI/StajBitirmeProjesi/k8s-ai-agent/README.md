# k8s-ai-agent

Kubernetes cluster'larındaki sorunlu podları otomatik tespit eden, ilgili log/event verisini hassas bilgi açısından güvenli hale getiren ve Google Gemini ile kök neden analizi + çözüm önerisi üreten bir DevOps/AIOps aracı.

Staj kapsamında "Kubernetes loglarını yorumlayan ve CrashLoopBackOff gibi durumları tespit/analiz eden bir yapay zeka aracı" hedefiyle geliştirilmiştir.

---

## Proje Ne Yapar

DevOps mühendisleri normalde bir podun neden `CrashLoopBackOff`, `OOMKilled` veya `ImagePullBackOff` durumuna düştüğünü anlamak için `kubectl describe` ve `kubectl logs --previous` çıktılarını elle okur, yorumlar.

**k8s-ai-agent** bu süreci otomatikleştirir:

1. Cluster'ı tarar, sorunlu podları kendisi bulur.
2. İlgili event ve log verisini kendisi çeker.
3. Bu veriyi LLM'e göndermeden önce hassas verileri (IP, şifre, token, secret) maskeler.
4. Gemini'den kök neden, güven seviyesi ve önerilen `kubectl` komutlarını yapılandırılmış JSON formatta alır.
5. Sonucu terminalde renkli panel/tablo olarak gösterir.

Araç **hiçbir işlemi otomatik uygulamaz** — sadece analiz eder ve önerir, uygulama kararı kullanıcıya aittir.

---

## Mimari

```
Kubernetes Cluster
        │  (kubernetes python client)
        ▼
collector.py   → sorunlu podları bulur, event/log çeker        [Aşama 1]
        │
        ▼
masker.py      → IP, secret, token'ları regex ile maskeler      [Aşama 2]
        │
        ▼
llm_client.py  → Gemini'ye gönderir, yapılandırılmış JSON alır  [Aşama 3]
        │
        ▼
cli.py         → Typer + Rich ile terminalde gösterir           [Aşama 4]
```

Her aşama kendi dosyasında, birbirinden bağımsız test edilebilir fonksiyonlar olarak yazılmıştır.

---

## Özellikler

- Tüm namespace'lerde `CrashLoopBackOff`, `OOMKilled`, `Error`, `ImagePullBackOff` durumundaki podları otomatik bulur.
- `last_state` kontrolü sayesinde şu an `Running` görünen ama yakın zamanda crash olmuş podları da yakalar.
- LLM'e gitmeden önce IP adresleri, `password=`/`api_key=`/`secret=` alanları, `Bearer` token'ları ve olası base64 secret'lar maskelenir.
- LLM çıktısı sabit bir JSON şemasında alınır (`root_cause`, `confidence`, `error_category`, `explanation`, `suggested_actions`) — güvenilir parse ve tutarlı terminal gösterimi sağlar.
- Panelde gösterilen "Kategori", LLM'in tahminine değil `collector.py`'nin Kubernetes API'sinden okuduğu **gerçek** `reason` alanına dayanır.
- Cluster'a bağlanılamazsa ya da LLM geçersiz JSON dönerse program çökmez, anlaşılır bir hata mesajı gösterir.
- Rich ile güven seviyesine göre renklendirilmiş paneller ve önerilen komut tabloları.

---

## Kurulum

**Ön koşullar:** Python 3.10+, Docker Desktop, [kind](https://kind.sigs.k8s.io/), `kubectl`, ücretsiz bir [Google AI Studio](https://aistudio.google.com/apikey) API key'i.

```powershell
cd k8s-ai-agent

python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

# proje kök dizininde .env dosyası oluştur:
# GEMINI_API_KEY=senin_api_keyin

kind create cluster --name devops-agent
```

---

## Kullanım

```powershell
# Tüm cluster'ı tara ve analiz et
python agent\cli.py

# Belirli bir namespace'i tara
python agent\cli.py --namespace default

# Modülleri tek tek test etme (geliştirme/debug amaçlı)
python agent\collector.py
python agent\masker.py
python agent\llm_client.py
```

Sorunlu pod yoksa: `Sorunlu pod bulunamadı. Cluster temiz görünüyor.` mesajı basılır.

---

## Proje Yapısı

```
k8s-ai-agent/
├── agent/
│   ├── collector.py      # Aşama 1: K8s API ile veri toplama
│   ├── masker.py          # Aşama 2: Hassas veri maskeleme
│   ├── llm_client.py      # Aşama 3: Gemini entegrasyonu
│   └── cli.py              # Aşama 4: Typer + Rich CLI
├── tests/                  # Kasıtlı hata üreten test manifestleri
├── .env                    # (git'e dahil değil) Gemini API key
├── .gitignore
├── requirements.txt
└── README.md
```

---

## Test Senaryoları ve Sonuçlar

| # | Senaryo | Gerçek Sebep | LLM Teşhisi | Sonuç |
|---|---|---|---|---|
| 1 | `broken-crashloop.yaml` | CrashLoopBackOff | Kasıtlı exit, PID 1 sonlanması | ✅ Doğru |
| 2 | `broken-imagepull.yaml` | ImagePullBackOff | İmaj bulunamadı / yanlış tag | ✅ Doğru |
| 3 | `broken-oomkilled.yaml` | OOMKilled | Bellek limiti aşımı (Exit Code 137) | ✅ Doğru |
| 4 | `broken-livenessprobe.yaml` | Liveness probe fail | Portta servis yok, connection refused | ✅ Doğru |
| 5 | Gerçek cluster hatası (organik) | API erişim hatası | API bağlantı zaman aşımı | ✅ Tutarlı |

**Sonuç: 5/5 senaryoda doğru kök neden ve doğru hata kategorisi tespit edilmiştir.**

```powershell
kubectl apply -f tests\broken-crashloop.yaml
kubectl apply -f tests\broken-oomkilled.yaml
kubectl apply -f tests\broken-imagepull.yaml
kubectl apply -f tests\broken-livenessprobe.yaml

kubectl get pods -w        # hata durumuna düşmeleri için ~30-60 sn bekle
python agent\cli.py

kubectl delete -f tests\broken-crashloop.yaml -f tests\broken-oomkilled.yaml -f tests\broken-imagepull.yaml -f tests\broken-livenessprobe.yaml
```

---

## Güvenlik Notları

- Log/event verisi **LLM'e gönderilmeden önce** `masker.py` tarafından işlenir; ham veri hiçbir zaman dış servise gitmez.
- `.env` dosyası `.gitignore` ile sürüm kontrolünün dışında tutulur, GitHub'a yüklenmez.
- Araç cluster üzerinde otomatik hiçbir değişiklik yapmaz (read-only); önerilen komutları uygulamak tamamen kullanıcının kararıdır.

---

## Bilinen Sınırlamalar

- **Regex tabanlı maskeleme yanlış pozitif üretebilir** (örn. pod UID'lerini de maskeleyebilir). Bu bilinçli bir trade-off: amaç hiçbir gerçek secret'ı kaçırmamak, fazladan maskeleme zararsız.
- **LLM'in `error_category` tahmini** bazen genelleme yapabilir; bu yüzden panelde gösterilen kategori LLM'in değil, Kubernetes API'sinden gelen gerçek `reason` değeridir.
- **Fine-tuning yerine prompt engineering** kullanılmıştır: etiketli bir eğitim veri seti yoktu, ve CrashLoopBackOff/OOMKilled gibi hatalar zaten güçlü modellerin genel bilgisiyle iyi çözülebiliyor — fine-tuning'in getirdiği ek maliyet/karmaşıklık bu proje ölçeğinde gerekli değildi.
- Ücretsiz API katmanı kullanıldığından günlük istek limiti vardır, prodüksiyon ölçeğine doğrudan uygun değildir.

---

## Geliştirilebilecek Noktalar

- Metrik entegrasyonu (`kubectl top pod`) ile OOMKilled teşhislerini güçlendirmek.
- RAG: bilinen K8s runbook'larını vektör veritabanına indekleyip LLM'e ek bağlam sunmak.
- Ölçülebilir bir eval scripti ile her senaryo için beklenen/gerçek sonuç karşılaştırması.
- Kullanıcı onaylı, isteğe bağlı bir `--auto-fix` modu.