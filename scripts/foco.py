#!/usr/bin/env python3
"""Sessões de foco: parser único da tabela, totais, alvos, melhores marcas e ritmo.

A tabela é Markdown, uma linha por sessão terminada:

    | Data       | Hora  | Categoria | Minutos | Fonte  |
    |------------|-------|-----------|---------|--------|
    | 2030-03-04 | 21:10 | leitura   | 50      | manual |
    | 2030-03-04 | 00:40 | codigo    | 50      | claude |
    | 2030-03-05 | 18:00 | escrita   | 15      | manual |

- Data = o **dia de foco** a que a sessão pertence; Hora = hora do relógio em que terminou.
- Dia de foco não vira à meia-noite, e sim na `virada_hora` da configuração. Uma hora antes
  da virada quer dizer "depois da meia-noite, ainda no dia de foco da coluna Data" (a segunda
  linha acima terminou às 00:40 do dia 05 e conta para o dia 04).
- Minutos = duração da sessão (o comando `registrar` usa a duração padrão se nada for dito).
- Categoria = uma das configuradas, ou `?` (a definir).

Uso:
  foco.py resumo [--desde AAAA-MM-DD] [--ate AAAA-MM-DD]
  foco.py dias   [--desde ...] [--ate ...]
  foco.py ritmo  [--agora AAAA-MM-DDTHH:MM] [--sempre]
  foco.py registrar CATEGORIA [--minutos N] [--fonte F] [--agora ...] [--dry-run]
"""
from __future__ import annotations

import argparse
import calendar
import collections
import datetime as dt
import hashlib
import math
import re
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comum import DIAS, ErroConfig, Foco, carregar_config, gravar_atomico, trava  # noqa: E402

COLUNAS = ["data", "hora", "categoria", "minutos", "fonte"]
CABECALHO = "| Data | Hora | Categoria | Minutos | Fonte |"
SEPARADOR = "|---|---|---|---|---|"
_HORA = re.compile(r"^(\d{2}):(\d{2})$")
_FONTE = re.compile(r"^[\w-]{1,32}$")
_SEPARADOR = re.compile(r"^\|(\s*:?-+:?\s*\|)+$")
MINUTOS_DIA = 24 * 60
MAX_MINUTOS = 12 * 60


class LinhaInvalida(ValueError):
    def __init__(self, linha: int, motivo: str, texto: str):
        super().__init__(f"linha {linha}: {motivo}: {texto!r}")
        self.linha = linha


@dataclass(frozen=True)
class Sessao:
    dia: dt.date          # dia de foco
    fim: int              # minutos desde 00:00 do dia de foco (depois da meia-noite passa de 1440)
    categoria: str
    minutos: int
    fonte: str


# ---------------------------------------------------------------- leitura

def ler(texto: str, cfg: Foco) -> list[Sessao]:
    """Lê as linhas de dado da tabela. Linha de tabela malformada levanta `LinhaInvalida`."""
    sessoes = []
    for n, bruta in enumerate(texto.splitlines(), 1):
        linha = bruta.strip()
        if not linha.startswith("|") or _SEPARADOR.match(linha):
            continue
        celulas = [c.strip() for c in linha.strip("|").split("|")]
        if [c.lower() for c in celulas] == COLUNAS:
            continue
        sessoes.append(_linha(n, linha, celulas, cfg))
    return sessoes


def _linha(n: int, linha: str, celulas: list[str], cfg: Foco) -> Sessao:
    if len(celulas) != len(COLUNAS):
        raise LinhaInvalida(n, f"esperava {len(COLUNAS)} colunas, achei {len(celulas)}", linha)
    data, hora, categoria, minutos, fonte = celulas
    try:
        dia = dt.date.fromisoformat(data)
    except ValueError:
        raise LinhaInvalida(n, "data não é AAAA-MM-DD", linha) from None
    m = _HORA.match(hora)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise LinhaInvalida(n, "hora não é HH:MM", linha)
    if not categoria:
        raise LinhaInvalida(n, "categoria vazia (use ? se ainda não sabe)", linha)
    if cfg.categorias and categoria != "?" and categoria not in cfg.categorias:
        raise LinhaInvalida(n, f"categoria fora da lista {list(cfg.categorias)}", linha)
    if not minutos.isdigit() or not 1 <= int(minutos) <= MAX_MINUTOS:
        raise LinhaInvalida(n, f"minutos deve ser um inteiro de 1 a {MAX_MINUTOS}", linha)
    if not _FONTE.match(fonte):
        raise LinhaInvalida(n, "fonte deve ser uma palavra", linha)
    hh, mm = int(m.group(1)), int(m.group(2))
    fim = hh * 60 + mm + (MINUTOS_DIA if hh < cfg.virada_hora else 0)
    return Sessao(dia, fim, categoria, int(minutos), fonte)


def ler_arquivo(caminho: Path, cfg: Foco) -> list[Sessao]:
    return ler(caminho.read_text(encoding="utf-8"), cfg)


# ---------------------------------------------------------------- dia de foco e registro

def dia_de_foco(agora: dt.datetime, virada_hora: int) -> tuple[dt.date, int]:
    """(dia de foco, minutos desde 00:00 desse dia). Antes da virada, ainda é o dia anterior."""
    minuto = agora.hour * 60 + agora.minute
    if agora.hour < virada_hora:
        return agora.date() - dt.timedelta(days=1), minuto + MINUTOS_DIA
    return agora.date(), minuto


def linha_nova(agora: dt.datetime, categoria: str, minutos: int, fonte: str, cfg: Foco) -> str:
    dia, _ = dia_de_foco(agora, cfg.virada_hora)
    linha = f"| {dia.isoformat()} | {agora:%H:%M} | {categoria} | {minutos} | {fonte} |"
    _linha(0, linha, [c.strip() for c in linha.strip("|").split("|")], cfg)  # valida antes de gravar
    return linha


def registrar(caminho: Path, linha: str, lock: Path) -> None:
    """Acrescenta a linha no fim da tabela (cria a tabela se não existe), sob lock."""
    with trava(lock, espera_s=10):
        texto = caminho.read_text(encoding="utf-8") if caminho.exists() else f"{CABECALHO}\n{SEPARADOR}\n"
        if not texto.endswith("\n"):
            texto += "\n"
        gravar_atomico(caminho, texto + linha + "\n", modo=0o644)


# ---------------------------------------------------------------- totais

def assinatura(sessoes: list[Sessao]) -> str:
    """sha256 do conteúdo normalizado das sessões: muda com qualquer correção (minutos, hora,
    categoria, fonte), não só com sessão nova."""
    linhas = sorted(f"{s.dia}|{s.fim}|{s.categoria}|{s.minutos}|{s.fonte}" for s in sessoes)
    return hashlib.sha256("\n".join(linhas).encode()).hexdigest()


def h(minutos: float) -> str:
    return f"{minutos / 60:.1f} h"


def por_dia(sessoes: list[Sessao]) -> dict[dt.date, int]:
    total: dict[dt.date, int] = collections.defaultdict(int)
    for s in sessoes:
        total[s.dia] += s.minutos
    return dict(total)


def por_categoria(sessoes: list[Sessao]) -> collections.Counter:
    c: collections.Counter = collections.Counter()
    for s in sessoes:
        c[s.categoria] += s.minutos
    return c


def semana(d: dt.date) -> tuple[int, int]:
    return d.isocalendar()[:2]


def mes(d: dt.date) -> tuple[int, int]:
    return d.year, d.month


def agrupar(total_dia: dict[dt.date, int], chave) -> collections.Counter:
    c: collections.Counter = collections.Counter()
    for d, mi in total_dia.items():
        c[chave(d)] += mi
    return c


def melhor(total_dia: dict[dt.date, int], chave, excluir) -> tuple[object, int]:
    """(período, minutos) do maior período, sem contar o período `excluir` (o atual)."""
    soma = agrupar(total_dia, chave)
    soma.pop(excluir, None)
    if not soma:
        return None, 0
    return max(soma.items(), key=lambda kv: (kv[1], kv[0]))


def filtrar(sessoes: list[Sessao], desde: dt.date | None, ate: dt.date | None) -> list[Sessao]:
    return [s for s in sessoes if (not desde or s.dia >= desde) and (not ate or s.dia <= ate)]


def texto_resumo(sessoes: list[Sessao]) -> str:
    if not sessoes:
        return "sem dado"
    dias = por_dia(sessoes)
    total = sum(dias.values())
    linhas = [f"Período: {min(dias)} a {max(dias)} · {len(dias)} dias com foco",
              f"Total: {len(sessoes)} sessões, {h(total)}", "", "Categoria       horas"]
    linhas += [f"{k:<14}{v / 60:>7.1f}" for k, v in por_categoria(sessoes).most_common()]
    linhas += ["", "Semana (seg)    horas"]
    for (a, w), v in sorted(agrupar(dias, semana).items()):
        linhas.append(f"{dt.date.fromisocalendar(a, w, 1)}  {v / 60:>7.1f}")
    return "\n".join(linhas)


def texto_dias(sessoes: list[Sessao]) -> str:
    return "\n".join(f"{d} {DIAS[d.weekday()]}  {h(v):>7}" for d, v in sorted(por_dia(sessoes).items())) or "sem dado"


# ---------------------------------------------------------------- ritmo

@dataclass(frozen=True)
class Ritmo:
    hoje: dt.date
    agora_min: int
    total: dict[dt.date, int]   # só o que já aconteceu até `agora`
    feito_hoje: int
    ritmo: float                # minutos de foco por minuto de relógio desde a 1ª sessão de hoje
    parar: float                # minuto em que costuma parar nesse dia da semana
    projecao_hoje: float
    normal: tuple[float, ...]   # média por dia da semana nas últimas semanas (dia sem sessão conta 0)


def calcular_ritmo(sessoes: list[Sessao], agora: dt.datetime, cfg: Foco) -> Ritmo:
    hoje, agora_min = dia_de_foco(agora, cfg.virada_hora)
    passadas = [s for s in sessoes if s.dia < hoje or (s.dia == hoje and s.fim <= agora_min)]
    total = por_dia(passadas)
    de_hoje = [s for s in passadas if s.dia == hoje]
    feito = total.get(hoje, 0)

    def mesmos_dias(dia_semana: int) -> list[dt.date]:
        ultimo = hoje - dt.timedelta(days=(hoje.weekday() - dia_semana) % 7 or 7)
        return [ultimo - dt.timedelta(weeks=k) for k in range(cfg.semanas_normal)]

    normal = tuple(sum(total.get(d, 0) for d in mesmos_dias(w)) / cfg.semanas_normal for w in range(7))
    fins: dict[dt.date, int] = {}
    for s in passadas:
        if s.dia < hoje:
            fins[s.dia] = max(fins.get(s.dia, 0), s.fim)
    amostra = [d for d in mesmos_dias(hoje.weekday()) if d in fins]
    if len(amostra) < 2:
        amostra = sorted(fins)[-30:]
    parar = statistics.median(fins[d] for d in amostra) if amostra else agora_min
    if de_hoje:
        inicio = min(s.fim - s.minutos for s in de_hoje)
        ritmo = min(1.0, feito / max(agora_min - inicio, 1))
    else:
        ritmo = 0.0
    proj = feito + ritmo * max(0, parar - agora_min)
    return Ritmo(hoje, agora_min, total, feito, ritmo, parar, proj, normal)


def _relogio(minutos: float) -> str:
    m = int(minutos)
    return f"{m // 60 % 24:02d}:{m % 60:02d}"


def _plural(n: int, singular: str, plural: str | None = None) -> str:
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


def linhas_ritmo(sessoes: list[Sessao], agora: dt.datetime, cfg: Foco, sempre: bool = False) -> list[str]:
    r = calcular_ritmo(sessoes, agora, cfg)
    w = r.hoje.weekday()
    dur = cfg.duracao_min
    fim_do_dia = MINUTOS_DIA + cfg.virada_hora * 60

    def quando(minuto: float) -> str:
        return f"às {_relogio(minuto)}" if minuto < fim_do_dia else "não cabe mais neste dia de foco"

    saida = []
    alvo = cfg.alvo_dia_min[w]
    falta = alvo - r.feito_hoje
    txt = f"Hoje ({DIAS[w]} {r.hoje}): {h(r.feito_hoje)} de {h(alvo)}"
    if falta <= 0:
        txt += f" · alvo atingido (+{h(-falta)})"
    else:
        n = math.ceil(falta / dur)
        limite = r.parar - n * dur
        txt += f" · faltam {_plural(n, 'bloco')} de {dur} min; em sequência, termina {quando(r.agora_min + n * dur)}"
        txt += (f"; para terminar até ~{_relogio(r.parar)} (horário habitual), comece até {_relogio(limite)}"
                if limite >= r.agora_min else f"; já não dá para terminar até ~{_relogio(r.parar)}")
    saida.append(txt + f" · média de {DIAS[w]}: {h(r.normal[w])}")

    alvo_s = cfg.alvo_semana_min
    feito_s = sum(v for d, v in r.total.items() if semana(d) == semana(r.hoje))
    saldo = feito_s - sum(cfg.alvo_dia_min[:w + 1])
    situacao = "no ritmo" if saldo == 0 else f"{'à frente' if saldo > 0 else 'atrás'} {h(abs(saldo))}"
    txt = f"Semana: {h(feito_s)} de {h(alvo_s)} · {situacao}"
    if feito_s >= alvo_s:
        txt += " · alvo atingido"
    else:
        restantes = 7 - w
        n = math.ceil((alvo_s - feito_s) / dur)
        txt += (f" · faltam {_plural(n, 'bloco')} em {_plural(restantes, 'dia')} (hoje incluso)"
                f" ≈ {math.ceil(n / restantes)}/dia")
    saida.append(txt)

    # melhor dia
    outros = {d: v for d, v in r.total.items() if d != r.hoje}
    if outros:
        top_d = max(outros, key=lambda d: (outros[d], d))
        top = outros[top_d]
        falta = top - r.feito_hoje
        perto = (r.feito_hoje > top or falta <= cfg.perto_dia_blocos * dur
                 or (r.feito_hoje >= 3 * dur and r.projecao_hoje >= top))
        if perto or sempre:
            if r.feito_hoje > top:
                det = f"novo melhor dia (antes: {h(top)} em {top_d})"
            elif falta == 0:
                det = f"empatou com o melhor dia ({h(top)}, {top_d}); mais um bloco e passa"
            else:
                n = math.ceil(falta / dur)
                det = (f"faltam {h(falta)} para o melhor dia ({h(top)}, {top_d}); "
                       f"em sequência, passa {quando(r.agora_min + n * dur)}")
            saida.append(f"{'[perto] ' if perto else ''}Melhor dia: {h(r.feito_hoje)} feitas · "
                         f"ritmo {r.ritmo:.0%} · projeção {h(r.projecao_hoje)} · {det}")

    # melhor semana e mês: projeção = média por dia até agora estendida ao período
    dias_mes = calendar.monthrange(r.hoje.year, r.hoje.month)[1]
    for nome, chave, passados, total_p, minimo, rotulo in (
            ("Melhor semana", semana, r.hoje.isoweekday(), 7, 3,
             lambda k: f"semana de {dt.date.fromisocalendar(k[0], k[1], 1)}"),
            ("Melhor mês", mes, r.hoje.day, dias_mes, 7, lambda k: f"{k[1]:02d}/{k[0]}")):
        atual = chave(r.hoje)
        feito = agrupar(r.total, chave).get(atual, 0)
        top_k, top = melhor(r.total, chave, atual)
        if not top:
            continue
        proj = ((feito - r.feito_hoje + r.projecao_hoje) / passados * total_p) if passados >= minimo else None
        perto = feito > top or top - feito <= cfg.perto_pct * top or (proj is not None and proj >= top)
        if not (perto or sempre):
            continue
        if feito > top:
            det = f"passou o anterior ({h(top)}, {rotulo(top_k)})"
        else:
            restantes = total_p - passados + 1
            n = math.ceil((top - feito) / dur)
            det = (f"faltam {h(top - feito)} para {h(top)} ({rotulo(top_k)}) ≈ "
                   f"{_plural(math.ceil(n / restantes), 'bloco')}/dia")
        p = f"projeção {h(proj)}" if proj is not None else f"projeção a partir do {minimo}º dia"
        saida.append(f"{'[perto] ' if perto else ''}{nome}: {h(feito)} feitas · {p} · {det}")
    return saida


# ---------------------------------------------------------------- CLI

def _data(s: str) -> dt.date:
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"data inválida: {s!r} (use AAAA-MM-DD)") from None


def _momento(s: str) -> dt.datetime:
    try:
        return dt.datetime.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"momento inválido: {s!r} (use AAAA-MM-DDTHH:MM)") from None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sessões de foco: totais, alvos, melhores marcas e registro.")
    ap.add_argument("--config", help="arquivo de configuração (padrão: $CLAUDE_BRAIN_CONFIG ou config.toml)")
    sub = ap.add_subparsers(dest="comando", required=True)
    for nome in ("resumo", "dias"):
        s = sub.add_parser(nome)
        s.add_argument("--desde", type=_data)
        s.add_argument("--ate", type=_data)
    s = sub.add_parser("ritmo")
    s.add_argument("--agora", type=_momento)
    s.add_argument("--sempre", action="store_true", help="mostra as melhores marcas mesmo longe delas")
    s = sub.add_parser("registrar")
    s.add_argument("categoria")
    s.add_argument("--minutos", type=int, help="duração (padrão: foco.duracao_min)")
    s.add_argument("--fonte", default="manual")
    s.add_argument("--agora", type=_momento)
    s.add_argument("--dry-run", action="store_true", help="mostra a linha sem gravar")
    a = ap.parse_args(argv)

    try:
        cfg = carregar_config(a.config)
    except ErroConfig as e:
        print(f"erro de configuração: {e}", file=sys.stderr)
        return 2
    tabela = cfg.foco.tabela

    if a.comando == "registrar":
        agora = a.agora or cfg.agora()
        try:
            linha = linha_nova(agora, a.categoria, a.minutos or cfg.foco.duracao_min, a.fonte, cfg.foco)
        except LinhaInvalida as e:
            print(f"não registrei: {e}", file=sys.stderr)
            return 2
        if a.dry_run:
            print(f"DRY-RUN: acrescentaria em {tabela.name}: {linha}")
            return 0
        try:
            registrar(tabela, linha, cfg.estado_dir / "foco.lock")
        except TimeoutError:
            print("outra gravação da tabela está em andamento; tente de novo", file=sys.stderr)
            return 1
        print(linha)
        return 0

    try:
        sessoes = ler_arquivo(tabela, cfg.foco)
    except FileNotFoundError:
        print(f"tabela não encontrada: {tabela}", file=sys.stderr)
        return 2
    except LinhaInvalida as e:
        print(f"tabela inválida ({tabela.name}): {e}", file=sys.stderr)
        return 2

    if a.comando == "ritmo":
        print("\n".join(linhas_ritmo(sessoes, a.agora or cfg.agora().replace(tzinfo=None), cfg.foco, a.sempre)))
    elif a.comando == "dias":
        print(texto_dias(filtrar(sessoes, a.desde, a.ate)))
    else:
        print(texto_resumo(filtrar(sessoes, a.desde, a.ate)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
