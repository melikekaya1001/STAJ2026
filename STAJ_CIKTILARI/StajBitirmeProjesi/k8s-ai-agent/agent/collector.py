"""
collector.py
Aşama 1: Kubernetes API İletişimi (Veri Toplama)

Bu modül:
  - Cluster'a bağlanır (kubeconfig üzerinden)
  - Tüm namespace'lerdeki podları tarar
  - Durumu CrashLoopBackOff, OOMKilled veya Error olan podları bulur
  - Bulunan her sorunlu pod için event geçmişini ve önceki (--previous) loglarını çeker
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from kubernetes import client, config
from kubernetes.client.rest import ApiException

# Sorunlu kabul ettiğimiz durum/sebep etiketleri
PROBLEM_REASONS = {"CrashLoopBackOff", "OOMKilled", "Error", "ImagePullBackOff", "ErrImagePull"}


@dataclass
class ProblemPod:
    """Sorunlu bulunan bir pod hakkındaki toplanmış ham veri."""

    namespace: str
    pod_name: str
    container_name: str
    reason: str                     # CrashLoopBackOff / OOMKilled / Error / ImagePullBackOff ...
    restart_count: int
    node_name: Optional[str] = None
    events: list[str] = field(default_factory=list)
    previous_logs: str = ""
    current_logs: str = ""


def load_kube_config(context: Optional[str] = None) -> None:
    """
    Kubeconfig'i yükler. Önce lokal ~/.kube/config dener,
    olmazsa (pod içinde çalışıyorsa) in-cluster config dener.
    """
    try:
        config.load_kube_config(context=context)
    except config.config_exception.ConfigException:
        config.load_incluster_config()


def _get_reason_from_container_status(cs: client.V1ContainerStatus) -> Optional[str]:
    """
    Bir container status objesinden anlamlı bir 'reason' çıkarır.
    Hem 'waiting' (örn. CrashLoopBackOff, ImagePullBackOff) hem de
    'terminated' (örn. OOMKilled, Error) durumlarını kontrol eder.
    """
    if cs.state.waiting is not None and cs.state.waiting.reason:
        if cs.state.waiting.reason in PROBLEM_REASONS:
            return cs.state.waiting.reason

    if cs.state.terminated is not None and cs.state.terminated.reason:
        if cs.state.terminated.reason in PROBLEM_REASONS:
            return cs.state.terminated.reason

    # last_state'de kalmış olabilir (pod şu an Running ama kısa süre önce crash oldu)
    if cs.last_state and cs.last_state.terminated is not None and cs.last_state.terminated.reason:
        if cs.last_state.terminated.reason in PROBLEM_REASONS:
            return cs.last_state.terminated.reason

    return None


def find_problem_pods(v1: client.CoreV1Api, namespace: Optional[str] = None) -> list[ProblemPod]:
    """
    Belirtilen namespace'de (None ise tüm cluster'da) sorunlu podları tarar.
    """
    problems: list[ProblemPod] = []

    if namespace:
        pods = v1.list_namespaced_pod(namespace=namespace).items
    else:
        pods = v1.list_pod_for_all_namespaces().items

    for pod in pods:
        ns = pod.metadata.namespace
        name = pod.metadata.name
        node_name = pod.spec.node_name if pod.spec else None

        statuses = pod.status.container_statuses or []
        for cs in statuses:
            reason = _get_reason_from_container_status(cs)
            if reason:
                problems.append(
                    ProblemPod(
                        namespace=ns,
                        pod_name=name,
                        container_name=cs.name,
                        reason=reason,
                        restart_count=cs.restart_count,
                        node_name=node_name,
                    )
                )

    return problems


def fetch_events_for_pod(v1: client.CoreV1Api, namespace: str, pod_name: str, limit: int = 15) -> list[str]:
    """
    'kubectl describe pod' çıktısındaki Events bölümüne karşılık gelen veriyi çeker.
    """
    try:
        events = v1.list_namespaced_event(
            namespace=namespace,
            field_selector=f"involvedObject.name={pod_name}",
        ).items
    except ApiException:
        return []

    events_sorted = sorted(
        events,
        key=lambda e: e.last_timestamp or e.event_time or e.metadata.creation_timestamp,
        reverse=True,
    )

    formatted = []
    for e in events_sorted[:limit]:
        ts = e.last_timestamp or e.event_time or e.metadata.creation_timestamp
        formatted.append(f"[{ts}] {e.type}/{e.reason}: {e.message}")

    return formatted


def fetch_logs_for_pod(
    v1: client.CoreV1Api,
    namespace: str,
    pod_name: str,
    container_name: str,
    tail_lines: int = 200,
) -> tuple[str, str]:
    """
    Hem mevcut (current) hem de önceki (--previous) container loglarını çeker.
    """
    current_logs = ""
    previous_logs = ""

    try:
        current_logs = v1.read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            container=container_name,
            tail_lines=tail_lines,
        )
    except ApiException as exc:
        current_logs = f"[log alinamadi: {exc.reason}]"

    try:
        previous_logs = v1.read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            container=container_name,
            previous=True,
            tail_lines=tail_lines,
        )
    except ApiException:
        previous_logs = ""

    return current_logs, previous_logs


def scan_cluster(namespace: Optional[str] = None, context: Optional[str] = None) -> list[ProblemPod]:
    """
    Ana giriş noktası: cluster'a bağlanır, sorunlu podları bulur,
    her biri için event ve log verisiyle zenginleştirir.
    """
    load_kube_config(context=context)
    v1 = client.CoreV1Api()

    problem_pods = find_problem_pods(v1, namespace=namespace)

    for p in problem_pods:
        p.events = fetch_events_for_pod(v1, p.namespace, p.pod_name)
        p.current_logs, p.previous_logs = fetch_logs_for_pod(
            v1, p.namespace, p.pod_name, p.container_name
        )

    return problem_pods


if __name__ == "__main__":
    # Hızlı manuel test: python collector.py
    results = scan_cluster()
    if not results:
        print("Sorunlu pod bulunamadi. Cluster temiz gorunuyor.")
    for pp in results:
        print("=" * 60)
        print(f"NS: {pp.namespace} | POD: {pp.pod_name} | REASON: {pp.reason} | RESTARTS: {pp.restart_count}")
        print("--- Events ---")
        for ev in pp.events:
            print(" ", ev)
        print("--- Previous Logs (son 200 satir) ---")
        print(pp.previous_logs[-1000:] if pp.previous_logs else "(yok)")