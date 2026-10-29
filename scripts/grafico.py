#!/usr/bin/env python3
"""Gráficos de sessões de foco para os relatórios (PNG, fundo claro) e o resumo em texto.

Uso:
  grafico.py semana AAAA-MM-DD --saida DIR   # semana ISO que contém a data → AAAA-Wnn-*.png
  grafico.py mes AAAA-MM --saida DIR         # mês → AAAA-MM-*.png
Imprime o resumo (que a rotina cola no pedido do relatório) e os caminhos gerados.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import foco  # noqa: E402
from comum import DIAS, ErroConfig, carregar_config  # noqa: E402

FUNDO, TEXTO, TEXTO2, GRADE = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1"
COR, COR_CLARA, COR_DESTAQUE = "#2a78d6", "#9ec5f4", "#1c5cab"


def _barras(rotulos, valores, cores, titulo, subtitulo, destino: Path) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "text.color": TEXTO,
                         "axes.labelcolor": TEXTO2, "xtick.color": TEXTO2, "ytick.color": TEXTO2})
    fig, ax = plt.subplots(figsize=(8, 3.6), dpi=150)
    fig.patch.set_facecolor(FUNDO)
    ax.set_facecolor(FUNDO)
    largura = min(0.6, 0.6 * 7 / max(len(rotulos), 7))
    ax.bar(range(len(rotulos)), valores, width=largura, color=cores, zorder=2)
    for i, v in enumerate(valores):
        if v > 0:
            ax.text(i, v, f"{v:.1f}".replace(".", ","), ha="center", va="bottom", fontsize=9, color=TEXTO2)
    ax.set_xticks(range(len(rotulos)), rotulos)
    ax.set_ylabel("horas")
    ax.grid(axis="y", color=GRADE, linewidth=0.8, zorder=0)
    for lado in ("top", "right", "left"):
        ax.spines[lado].set_visible(False)
    ax.spines["bottom"].set_color(GRADE)
    ax.tick_params(length=0)
    ax.set_ylim(0, max(max(valores, default=0) * 1.18, 1))
    fig.text(0.01, 0.97, titulo, fontsize=12, fontweight="bold", va="top")
    fig.text(0.01, 0.89, subtitulo, fontsize=9, color=TEXTO2, va="top")
    fig.tight_layout(rect=(0, 0, 1, 0.84))
    destino.parent.mkdir(parents=True, exist_ok=True)
    # sem versão no metadado (reprodutível) e com compressão máxima (arquivo menor)
    fig.savefig(destino, facecolor=FUNDO, metadata={"Software": None}, pil_kwargs={"compress_level": 9})
    plt.close(fig)
    return destino


def _categorias(sessoes) -> str:
    c = foco.por_categoria(sessoes)
    return "; ".join(f"{k} {v / 60:.1f} h" for k, v in c.most_common()) or "sem dado"


def semana(sessoes: list[foco.Sessao], data: dt.date, saida: Path | None) -> tuple[str, list[Path]]:
    """Resumo da semana ISO de `data` e, se `saida` for dada, dois PNGs (dias e últimas 12 semanas)."""
    ano, num, _ = data.isocalendar()
    seg = dt.date.fromisocalendar(ano, num, 1)
    dias = [seg + dt.timedelta(i) for i in range(7)]
    total = foco.por_dia(sessoes)
    horas = [total.get(d, 0) / 60 for d in dias]
    semanas = [seg - dt.timedelta(weeks=k) for k in range(11, -1, -1)]
    hs = [sum(total.get(s + dt.timedelta(i), 0) for i in range(7)) / 60 for s in semanas]
    anteriores = [v for v in hs[:-1] if v > 0]
    media = sum(anteriores) / len(anteriores) if anteriores else 0
    tag = f"{ano}-W{num:02d}"
    da_semana = [s for s in sessoes if seg <= s.dia <= dias[-1]]

    linhas = [f"semana {tag} ({seg} a {dias[-1]})"]
    linhas += [f"  {DIAS[i]} {d:%d/%m}: {v:.1f} h" for i, (d, v) in enumerate(zip(dias, horas, strict=True))]
    linhas += [f"  total: {sum(horas):.1f} h | média das semanas anteriores com registro: {media:.1f} h",
               f"  dias sem sessão: {sum(1 for v in horas if v == 0)} de 7",
               f"  por categoria: {_categorias(da_semana)}"]
    imagens = []
    if saida:
        imagens.append(_barras([f"{DIAS[i]}\n{d:%d/%m}" for i, d in enumerate(dias)], horas, [COR] * 7,
                               f"Horas de foco — semana {num} ({seg:%d/%m}–{dias[-1]:%d/%m})",
                               f"Total {sum(horas):.1f} h".replace(".", ","), saida / f"{tag}-dias.png"))
        imagens.append(_barras([f"{s:%d/%m}" for s in semanas], hs, [COR_CLARA] * 11 + [COR_DESTAQUE],
                               "Horas por semana — últimas 12",
                               f"Semana do relatório em destaque · média anterior {media:.1f} h".replace(".", ","),
                               saida / f"{tag}-historico.png"))
    return "\n".join(linhas), imagens


def mes(sessoes: list[foco.Sessao], ano: int, num: int, saida: Path | None) -> tuple[str, list[Path]]:
    """Resumo do mês e, se `saida` for dada, dois PNGs (semanas do mês e últimos 6 meses)."""
    ini = dt.date(ano, num, 1)
    fim = dt.date(ano + num // 12, num % 12 + 1, 1) - dt.timedelta(days=1)
    total = foco.por_dia(sessoes)
    minutos: dict[dt.date, int] = {}
    d = ini
    while d <= fim:
        s = d - dt.timedelta(days=d.weekday())
        minutos[s] = minutos.get(s, 0) + total.get(d, 0)
        d += dt.timedelta(days=1)
    semanas = {s: v / 60 for s, v in minutos.items()}
    meses = []
    for k in range(5, -1, -1):
        a, m = ano, num - k
        while m <= 0:
            a, m = a - 1, m + 12
        meses.append((a, m))
    hm = [sum(v for dd, v in total.items() if (dd.year, dd.month) == am) / 60 for am in meses]
    tag = f"{ano}-{num:02d}"
    do_mes = [s for s in sessoes if ini <= s.dia <= fim]

    linhas = [f"mês {tag}: {sum(minutos.values()) / 60:.1f} h"]
    linhas += [f"  semana de {s:%d/%m}: {v:.1f} h" for s, v in semanas.items()]
    linhas += [f"  {m:02d}/{a}: {v:.1f} h" for (a, m), v in zip(meses, hm, strict=True)]
    linhas.append(f"  por categoria: {_categorias(do_mes)}")
    imagens = []
    if saida:
        imagens.append(_barras([f"{s:%d/%m}" for s in semanas], list(semanas.values()), [COR] * len(semanas),
                               f"Horas por semana — {tag}", "Só os dias do mês", saida / f"{tag}-semanas.png"))
        imagens.append(_barras([f"{m:02d}/{a % 100}" for a, m in meses], hm, [COR_CLARA] * 5 + [COR_DESTAQUE],
                               "Horas por mês — últimos 6", "Mês do relatório em destaque",
                               saida / f"{tag}-meses.png"))
    return "\n".join(linhas), imagens


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Gráficos e resumo das sessões de foco.")
    ap.add_argument("--config")
    ap.add_argument("periodo", choices=["semana", "mes"])
    ap.add_argument("referencia", help="AAAA-MM-DD (semana) ou AAAA-MM (mês)")
    ap.add_argument("--saida", type=Path, help="pasta dos PNGs; sem ela, só o resumo em texto")
    a = ap.parse_args(argv)
    try:
        cfg = carregar_config(a.config)
        sessoes = foco.ler_arquivo(cfg.foco.tabela, cfg.foco)
        if a.periodo == "semana":
            texto, imagens = semana(sessoes, dt.date.fromisoformat(a.referencia), a.saida)
        else:
            ano, num = (int(x) for x in a.referencia.split("-"))
            if not 1 <= num <= 12:
                raise ValueError("mês fora de 1..12")
            texto, imagens = mes(sessoes, ano, num, a.saida)
    except (ErroConfig, foco.LinhaInvalida, OSError) as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"referência inválida {a.referencia!r}: {e}", file=sys.stderr)
        return 2
    print(texto)
    for p in imagens:
        print(f"img: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
