"""Leitura do vault: frontmatter, notas de projeto, links simbólicos e retrato para conferir mudanças.

Só biblioteca padrão (usado pelos hooks).
"""
from __future__ import annotations

import os
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from comum import dentro_de, validar_pasta

TIPOS_PRINCIPAIS = ("projeto", "tema")
CHAVES_PASTA = ("pasta", "outras_pastas")
_CHAVE = re.compile(r"^([A-Za-z_][\w-]*):\s*(.*)$")


def frontmatter(texto: str) -> dict[str, str | list[str]]:
    """Frontmatter YAML simples (chave: valor e listas `[a, b]`). Não é um parser YAML completo."""
    if not texto.startswith("---\n"):
        return {}
    bloco = texto[4:].split("\n---", 1)[0]
    fm: dict[str, str | list[str]] = {}
    for linha in bloco.splitlines():
        m = _CHAVE.match(linha)
        if not m:
            continue
        valor = m.group(2).strip()
        if valor.startswith("[") and valor.endswith("]") and "[[" not in valor:
            fm[m.group(1)] = [x.strip().strip("\"'") for x in valor[1:-1].split(",") if x.strip()]
        else:
            fm[m.group(1)] = valor.strip("\"'")
    return fm


def ler_frontmatter(caminho: Path) -> dict[str, str | list[str]]:
    try:
        with open(caminho, encoding="utf-8", errors="replace") as f:
            return frontmatter(f.read(4000))
    except OSError:
        return {}


def notas(vault: Path) -> Iterator[Path]:
    """Todas as notas `.md` do vault, sem pastas ocultas (`.obsidian`, `.git`, `.trash`)."""
    for raiz, dirs, arquivos in os.walk(vault):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for a in sorted(arquivos):
            if a.endswith(".md"):
                yield Path(raiz) / a


def pastas_da_nota(fm: dict, raizes: Iterable[Path] | None = None) -> tuple[list[Path], list[str]]:
    """Pastas válidas declaradas na nota e os motivos das rejeitadas."""
    validas, rejeitadas = [], []
    for chave in CHAVES_PASTA:
        valor = fm.get(chave)
        for bruto in valor if isinstance(valor, list) else ([valor] if valor else []):
            try:
                validas.append(validar_pasta(bruto, raizes))
            except ValueError as e:
                rejeitadas.append(f"{chave}: {e}")
    return validas, rejeitadas


def projeto_pela_pasta(vault: Path, cwd: str | os.PathLike, raizes: Iterable[Path] | None = None) -> Path | None:
    """Nota principal cuja `pasta:` (ou `outras_pastas:`) contém `cwd`; a pasta mais específica vence."""
    if not cwd or not os.path.isabs(cwd):
        return None
    raizes = list(raizes) if raizes is not None else None
    alvo = os.path.realpath(cwd)
    melhor: tuple[int, Path] | None = None
    for nota in notas(vault):
        fm = ler_frontmatter(nota)
        if fm.get("tipo") not in TIPOS_PRINCIPAIS:
            continue
        for pasta in pastas_da_nota(fm, raizes)[0]:
            p = str(pasta)
            if (alvo == p or alvo.startswith(p + os.sep)) and (not melhor or len(p) > melhor[0]):
                melhor = (len(p), nota)
    return melhor[1] if melhor else None


def marcador_sessao(session_id: str) -> re.Pattern:
    return re.compile(r"%%\s*sess[õo]es:[^%]*" + re.escape(session_id))


def notas_que_citam(vault: Path, session_id: str) -> list[Path]:
    """Notas com `%% sessões: ... <id> ... %%` (o marcador que a skill grava em cada entrada)."""
    marcador = marcador_sessao(session_id)
    achadas = []
    for nota in notas(vault):
        try:
            if marcador.search(nota.read_text(encoding="utf-8", errors="replace")):
                achadas.append(nota)
        except OSError:
            continue
    return achadas


def _oculto(rel: Path) -> bool:
    return any(parte.startswith(".") for parte in rel.parts)


def _dentro_de_algum(p: Path, permitidos: list[Path]) -> bool:
    return any(p == q or q in p.parents for q in permitidos)


def links_inseguros(pastas: Iterable[Path], base: Path) -> list[Path]:
    """Links simbólicos nos caminhos de escrita (ou que são eles mesmos) cujo destino fica fora
    de `base`, fora dos próprios caminhos de escrita, ou numa parte oculta do vault: escrever
    através deles chegaria onde a automação não pode escrever."""
    pastas = [Path(p) for p in pastas]
    base_real = Path(os.path.realpath(base))
    permitidos = [base_real / p.relative_to(base) for p in pastas]

    def inseguro(link: Path) -> bool:
        destino = Path(os.path.realpath(link))
        if not dentro_de(destino, base_real):
            return True
        return _oculto(destino.relative_to(base_real)) or not _dentro_de_algum(destino, permitidos)

    achados = [p for p in pastas if p.is_symlink() and inseguro(p)]
    for pasta in pastas:
        if not pasta.is_dir() or pasta.is_symlink():
            continue
        for raiz, dirs, arquivos in os.walk(pasta):
            for nome in dirs + arquivos:
                p = Path(raiz) / nome
                if p.is_symlink() and inseguro(p):
                    achados.append(p)
    return sorted(achados)


LIMITE_TEXTO_ANTERIOR = 1_000_000  # bytes; nota maior é tratada como nova na varredura


def textos_anteriores(caminhos: Iterable[Path], limite: int = LIMITE_TEXTO_ANTERIOR) -> dict[str, str]:
    """caminho absoluto → texto de cada `.md` (sem parte oculta) nos caminhos de escrita, antes da
    sessão automática. A varredura compara com ele para só bloquear o que a sessão acrescentou."""
    arquivos: list[Path] = []
    for c in caminhos:
        c = Path(c)
        if c.is_file():
            arquivos.append(c)
        elif c.is_dir():
            for raiz, dirs, nomes in os.walk(c):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                arquivos += [Path(raiz) / n for n in nomes if not n.startswith(".")]
    textos = {}
    for a in arquivos:
        try:
            if a.suffix == ".md" and not a.is_symlink() and a.stat().st_size <= limite:
                textos[str(a)] = a.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return textos


def retrato(pasta: Path) -> dict[str, tuple[int, int, int]]:
    """caminho relativo → (mtime_ns, tamanho, modo) de TODO arquivo e link da pasta, ocultos
    inclusive. Links não são seguidos. Serve para saber o que mudou durante uma sessão."""
    estado = {}
    if not pasta.is_dir():
        return estado
    for raiz, dirs, arquivos in os.walk(pasta):
        for nome in arquivos + [d for d in dirs if (Path(raiz) / d).is_symlink()]:
            p = Path(raiz) / nome
            try:
                st = p.lstat()
            except OSError:
                continue
            estado[str(p.relative_to(pasta))] = (st.st_mtime_ns, st.st_size, st.st_mode)
    return estado


def mudancas(antes: dict, depois: dict) -> list[str]:
    """Arquivos criados, alterados ou removidos entre dois retratos."""
    return sorted(k for k in set(antes) | set(depois) if antes.get(k) != depois.get(k))


INSTRUCOES_DE_AGENTE = ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md")
# Plugins cuja configuração (data.json) contém comandos ou código que eles executam; nos demais,
# data.json é só preferência e a mudança vira AVISO.
PLUGINS_QUE_EXECUTAM_A_CONFIG = ("obsidian-shellcommands", "templater-obsidian", "dataview", "execute-code",
                                 "buttons", "js-engine", "obsidian-git", "quickadd", "customjs")


def critico(rel: str) -> bool:
    """Caminho cuja mudança pode executar código ou instruir um agente depois: plugins e
    snippets do Obsidian, hooks e config do git, instruções de agente em qualquer pasta."""
    partes = Path(rel).parts
    if partes[:2] == (".obsidian", "plugins") and (
            partes[-1] != "data.json" or (len(partes) > 2 and partes[2] in PLUGINS_QUE_EXECUTAM_A_CONFIG)):
        return True
    if partes[:2] in ((".obsidian", "snippets"), (".git", "hooks")):
        return True
    if rel in (".obsidian/community-plugins.json", ".git/config"):
        return True
    return partes[-1] in INSTRUCOES_DE_AGENTE or ".claude" in partes


@dataclass(frozen=True)
class Classificacao:
    permitidos: list[str]   # dentro dos caminhos de escrita, sem parte oculta
    criticos: list[str]     # executam ou instruem: sempre FALHA, mesmo dentro do permitido
    avisos: list[str]       # fora do permitido, mas inofensivos (outro programa ou a pessoa)


def classificar(mudados: Iterable[str], base: Path, permitidos: Iterable[Path],
                ignorar: Iterable[str] = ()) -> Classificacao:
    permitidos = [Path(p) for p in permitidos]
    ignorar = set(ignorar)
    ok, criticos, avisos = [], [], []
    for rel in mudados:
        if critico(rel):
            criticos.append(rel)
        elif rel in ignorar:
            continue
        elif not _oculto(Path(rel)) and _dentro_de_algum(base / rel, permitidos):
            ok.append(rel)
        else:
            avisos.append(rel)
    return Classificacao(ok, criticos, avisos)
