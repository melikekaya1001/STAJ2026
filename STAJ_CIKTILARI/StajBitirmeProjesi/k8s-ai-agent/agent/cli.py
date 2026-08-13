"""
cli.py
Aşama 4: Komut Satırı Arayüzü (CLI)

Kullanım:
  python agent\\cli.py --scan
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.status import Status

from collector import scan_cluster
from masker import mask_problem_pod_data
from llm_client import diagnose_pod

app = typer.Typer()
console = Console()

# Güven seviyesine göre renk seçimi
CONFIDENCE_COLORS = {
    "high": "green",
    "medium": "yellow",
    "low": "red",
}


def render_diagnosis(pod_namespace: str, pod_name: str, reason: str, restart_count: int, result) -> None:
    """Tek bir podun teşhis sonucunu Rich paneli olarak ekrana basar."""
    color = CONFIDENCE_COLORS.get(result.confidence, "white")

    body = (
        f"[bold]Kök Neden:[/bold] {result.root_cause}\n\n"
        f"[bold]Açıklama:[/bold] {result.explanation}\n\n"
        f"[bold]Güven Seviyesi:[/bold] [{color}]{result.confidence}[/{color}]\n"
        f"[bold]Kategori:[/bold] {reason}"
    )

    console.print(
        Panel(
            body,
            title=f"[bold red]{pod_namespace}/{pod_name}[/bold red] — {reason} (restart: {restart_count})",
            border_style=color,
        )
    )

    if result.suggested_actions:
        table = Table(title="Önerilen Komutlar", show_lines=True)
        table.add_column("Komut", style="cyan", no_wrap=False)
        table.add_column("Neden", style="white")
        for action in result.suggested_actions:
            table.add_row(action.command, action.reason)
        console.print(table)

    console.print()  # boşluk


@app.command()
def scan(
    namespace: str = typer.Option(None, "--namespace", "-n", help="Sadece belirli bir namespace'i tara"),
):
    """
    Cluster'ı tarar, sorunlu podları bulur, maskeler ve LLM ile teşhis eder.
    """
    console.print("[bold cyan]k8s-ai-agent[/bold cyan] taramaya başlıyor...\n")

    # 1) Cluster tarama
    try:
        with console.status("[bold green]Cluster taranıyor...", spinner="dots"):
            problem_pods = scan_cluster(namespace=namespace)
    except Exception as exc:
        console.print(
            Panel(
                f"Cluster'a bağlanılamadı.\n\n"
                f"Kontrol et:\n"
                f"  1. Docker Desktop açık mı?\n"
                f"  2. kind cluster ayakta mı? ([cyan]kind get clusters[/cyan])\n\n"
                f"Teknik detay: {exc}",
                title="[bold red]Bağlantı Hatası[/bold red]",
                border_style="red",
            )
        )
        raise typer.Exit(code=1)

    if not problem_pods:
        console.print("[bold green]Sorunlu pod bulunamadı. Cluster temiz görünüyor.[/bold green]")
        raise typer.Exit(code=0)

    console.print(f"[bold yellow]{len(problem_pods)} sorunlu pod bulundu.[/bold yellow]\n")

    # 2) Her pod için maskeleme + LLM teşhisi
    for pod in problem_pods:
        with console.status(f"[bold green]{pod.pod_name} analiz ediliyor...", spinner="dots"):
            masked_events, masked_previous, masked_current, counts = mask_problem_pod_data(
                pod.events, pod.previous_logs, pod.current_logs
            )
            try:
                result = diagnose_pod(pod.reason, masked_events, masked_previous)
            except Exception as exc:
                console.print(
                    Panel(
                        f"LLM analizi başarısız oldu: {exc}",
                        title=f"[bold red]{pod.namespace}/{pod.pod_name}[/bold red]",
                        border_style="red",
                    )
                )
                continue

        render_diagnosis(pod.namespace, pod.pod_name, pod.reason, pod.restart_count, result)


if __name__ == "__main__":
    app()