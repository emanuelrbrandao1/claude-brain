#!/usr/bin/env python3
"""Gera os dados fictícios do exemplo e um ambiente de demonstração pronto para rodar.

1. `exemplo/vault/foco/Sessoes de foco.md`: tabela de sessões de foco gerada com seed fixa
   (sempre a mesma saída) e os dois gráficos que o relatório de exemplo embute. Os dois vão
   para o repositório.
2. `exemplo/saida/` (ignorado pelo git): cópia do vault com `pasta:` apontando para pastas de
   código fictícias, uma conversa fictícia no formato de transcrição do Claude Code, o payload
   do hook e um `config.toml` de demonstração.

Uso: .venv/bin/python exemplo/gerar_dados.py [--seed N]   (sem matplotlib, pula os gráficos)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import re
import shutil
import sys
import uuid
from pathlib import Path

AQUI = Path(__file__).resolve().parent
VAULT = AQUI / "vault"
SAIDA = AQUI / "saida"
INICIO = dt.date(2030, 2, 4)   # uma segunda-feira
SEMANAS = 10
CATEGORIAS = ("leitura", "escrita", "codigo")
VIRADA = 4      # mesma virada_hora da configuração de demonstração
DURACAO = 50
CABECALHO = """---
tipo: dados
---

# Sessões de foco

Uma linha por sessão terminada. Gerado por `exemplo/gerar_dados.py` (dados fictícios).
Data é o dia de foco; hora antes das 04:00 = depois da meia-noite, ainda nesse dia de foco.

| Data | Hora | Categoria | Minutos | Fonte |
|---|---|---|---|---|
"""


def tabela(seed: int) -> str:
    rnd = random.Random(seed)
    linhas = []
    for i in range(SEMANAS * 7):
        dia = INICIO + dt.timedelta(days=i)
        fim_de_semana = dia.weekday() >= 5
        n = rnd.choices(range(6), weights=(2, 2, 3, 3, 2, 1) if not fim_de_semana else (4, 3, 2, 1, 1, 0))[0]
        hora = rnd.choice((8, 9, 14, 19, 20))
        minuto = rnd.randrange(0, 60, 5)
        for _ in range(n):
            minuto += DURACAO + rnd.choice((0, 5, 10, 15))
            hora_fim, minuto_fim = hora + minuto // 60, minuto % 60
            if hora_fim >= 24 + VIRADA:   # passou da virada: o dia de foco acabou
                break
            categoria = rnd.choice(CATEGORIAS)
            fonte = rnd.choice(("manual", "claude"))
            linhas.append(f"| {dia} | {hora_fim % 24:02d}:{minuto_fim:02d} | {categoria} | {DURACAO} | {fonte} |")
        if n and rnd.random() < 0.15:
            linhas.append(f"| {dia} | 23:30 | leitura | {rnd.choice((10, 15, 20))} | manual |")

    def chave(linha: str):  # dia de foco e hora de fim (depois da meia-noite vem depois da noite)
        _, data, hora, *_ = (c.strip() for c in linha.split("|"))
        h, m = int(hora[:2]), int(hora[3:5])
        return data, (h + 24 if h < VIRADA else h) * 60 + m
    return CABECALHO + "\n".join(sorted(linhas, key=chave)) + "\n"


def transcricao(sid: str) -> str:
    """Conversa fictícia de dois dias, no formato JSON por linha da transcrição do Claude Code."""
    eventos = []

    def ev(tipo, quando, conteudo):
        eventos.append({"type": tipo, "timestamp": quando,
                        "message": {"role": tipo, "content": conteudo}, "sessionId": sid})

    ev("user", "2030-04-12T19:02:00Z", "O sensor de umidade da horta está lendo 100% o tempo todo. Por quê?")
    ev("assistant", "2030-04-12T19:03:00Z", [{"type": "text", "text": "Provável curto no divisor resistivo."},
                                             {"type": "tool_use", "name": "Read", "input": {}}])
    ev("user", "2030-04-15T20:10:00Z", "Troquei o resistor. Agora calibre os limites seco/molhado.")
    ev("assistant", "2030-04-15T20:12:00Z", [{"type": "text", "text": "Limites novos: seco 2900, molhado 1300."}])
    return "\n".join(json.dumps(e, ensure_ascii=False) for e in eventos) + "\n"


def ambiente_demo() -> None:
    if SAIDA.exists():
        shutil.rmtree(SAIDA)  # só a pasta de saída do próprio exemplo
    vault = SAIDA / "vault"
    shutil.copytree(VAULT, vault)
    codigo = SAIDA / "codigo"
    for nota in vault.rglob("*.md"):
        texto = nota.read_text(encoding="utf-8")
        novo = re.sub(r"^pasta: ~/projetos/(.+)$",
                      lambda m: f"pasta: {codigo / m.group(1)}", texto, flags=re.M)
        if novo != texto:
            nota.write_text(novo, encoding="utf-8")
    for nome in ("horta-sensores", "leitor-rss", "receitas-api"):
        (codigo / nome).mkdir(parents=True, exist_ok=True)

    sid = str(uuid.UUID(int=0x5EED))
    conversas = SAIDA / "conversas"
    conversas.mkdir()
    arq = conversas / f"{sid}.jsonl"
    arq.write_text(transcricao(sid), encoding="utf-8")
    (SAIDA / "payload.json").write_text(json.dumps({
        "session_id": sid, "transcript_path": str(arq), "cwd": str(codigo / "horta-sensores"),
        "hook_event_name": "SessionEnd", "reason": "prompt_input_exit"}, indent=1), encoding="utf-8")

    (SAIDA / "config.toml").write_text(f'''# Configuração de demonstração (gerada).
raizes = ["{AQUI.parent}"]
vault = "{vault}"
timezone = "UTC"
log_dir = "{SAIDA / 'logs'}"
estado_dir = "{SAIDA / 'estado'}"
claude_bin = "claude"

[autosave]
pastas = ["{codigo}"]

[[fontes]]
nome = "diarios"
caminho = "{AQUI / 'fontes' / 'diarios'}"

[rotina]
dia_relatorio = 1
commit = true

[foco]
tabela = "foco/Sessoes de foco.md"
duracao_min = {DURACAO}
virada_hora = {VIRADA}
alvo_dia_min = [100, 100, 100, 100, 100, 60, 60]
categorias = {json.dumps(list(CATEGORIAS))}

[email]
ativo = true
host = "smtp.exemplo.test"
usuario = "demo@exemplo.test"
destino = "demo@exemplo.test"

[privacidade]
emails_permitidos = ["@exemplo.test"]
''', encoding="utf-8")


def graficos() -> None:
    """Os dois PNGs da semana 2030-W14 que o relatório de exemplo embute."""
    sys.path.insert(0, str(AQUI.parent / "scripts"))
    try:
        import foco
        import grafico
    except ImportError as e:
        print(f"gráficos pulados ({e.name} não instalado; use o Python do .venv)")
        return
    from comum import Foco
    cfg = Foco(tabela=VAULT / "foco" / "Sessoes de foco.md", duracao_min=DURACAO, virada_hora=VIRADA)
    sessoes = foco.ler_arquivo(cfg.tabela, cfg)
    _, imagens = grafico.semana(sessoes, dt.date(2030, 4, 1), VAULT / "analise" / "relatorios" / "img")
    for p in imagens:
        print(f"gráfico: {p.relative_to(AQUI.parent)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seed", type=int, default=2030)
    a = ap.parse_args()
    destino = VAULT / "foco" / "Sessoes de foco.md"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(tabela(a.seed), encoding="utf-8")
    graficos()
    ambiente_demo()
    print(f"tabela: {destino.relative_to(AQUI.parent)}")
    print(f"ambiente de demonstração: {SAIDA.relative_to(AQUI.parent)}/ (config.toml, payload.json, vault/)")


if __name__ == "__main__":
    main()
