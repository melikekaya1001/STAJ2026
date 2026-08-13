"""
test_pipeline.py
Gecici test dosyasi: collector + masker + llm_client'in birlikte calistigini gormek icin.
"""

from collector import scan_cluster
from masker import mask_problem_pod_data
from llm_client import diagnose_pod

results = scan_cluster()

for pp in results:
    if pp.pod_name != "broken-crashloop":
        continue  # sadece test podumuza bakalim

    masked_events, masked_previous, masked_current, counts = mask_problem_pod_data(
        pp.events, pp.previous_logs, pp.current_logs
    )

    print("=" * 60)
    print(f"POD: {pp.pod_name} | REASON: {pp.reason}")
    print("Maskeleme sayaclari:", counts)
    print()

    result = diagnose_pod(pp.reason, masked_events, masked_previous)

    print("--- LLM Teshisi ---")
    print("Root cause:", result.root_cause)
    print("Confidence:", result.confidence)
    print("Category:", result.error_category)
    print("Explanation:", result.explanation)
    print("Suggested actions:")
    for a in result.suggested_actions:
        print(" -", a.command, "|", a.reason)