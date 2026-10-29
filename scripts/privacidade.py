#!/usr/bin/env python3
"""Varredura determinística de segredos, conteúdo executável e termos proibidos em arquivos de texto.

Roda nos arquivos que a automação escreveu, antes de qualquer commit ou envio. Não substitui
revisão humana: regex pega formato conhecido, não intenção. O que achar sai mascarado.

Conteúdo executável: uma nota pode carregar código que um plugin do Obsidian roda sozinho ao
abri-la ou ao aplicá-la como modelo (```dataviewjs, inline `$=…`, `<% … %>` do Templater, blocos
```run-…, ```button, ```js-engine). Em nota escrita pela automação isso é bloqueante. Bloco de
shell comum (```sh, ```bash…) só roda se a pessoa clicar para executar: vira aviso.

Uso:
  privacidade.py ARQUIVO... [--termos LISTA.txt] [--permitir-email EMAIL_OU_@DOMINIO ...]
Código de saída: 0 limpo, 1 achou algo, 2 erro de uso.
"""
from __future__ import annotations

import argparse
import collections
import dataclasses
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_INI = r"(?<![A-Za-z0-9])"   # começo de token sem depender de \b (que falha depois de _ e -)
_FIM = r"(?![A-Za-z0-9])"
_NOME = (r"(?:senha|password|passwd|passphrase|pwd|secret|segredo|token|api[_-]?key|access[_-]?key"
         r"|private[_-]?key|client[_-]?secret)")
_SEPARADOR = r"(?P<sep>[ \t]{0,5}(?::|=>|=|\|)[ \t]{0,5}|[ \t]{1,5}(?:é|eh|is|era)[ \t]{1,5})"
_VALOR = r"(?P<valor>\"[^\"\n]{4,200}\"|'[^'\n]{4,200}'|`[^`\n]{4,200}`|[^\s|'\"`]{6,200})"
# valor que é só o NOME de uma variável (SMTP_SENHA, $TOKEN, ${API_KEY}) não é segredo
_NOME_DE_VARIAVEL = re.compile(r"\$?\{?[A-Z][A-Z0-9_]*\}?")
# valor sem aspas que é palavra comum de prosa ou marcador de vazio
_PALAVRAS_COMUNS = {"nenhum", "nenhuma", "none", "null", "nil", "vazio", "vazia", "empty", "undefined",
                    "indefinido", "indefinida", "omitido", "omitida", "redacted", "removido", "removida"}
# Linha longa é varrida em janelas de JANELA caracteres que se sobrepõem em SOBREPOSICAO (maior que
# o maior casamento possível de senha atribuída e e-mail, ~330), para o custo por janela ser o de
# uma linha comum. Os padrões de formato fixo rodam na linha inteira (são lineares).
JANELA = 4000
SOBREPOSICAO = 400  # > maior casamento: senha atribuída ~360 (80+15+40+11+202), e-mail ~345 (64+1+255+1+24)

# Formato fixo: prefixo literal e comprimento limitado. Os limites superiores não perdem segredo
# (basta casar o começo) e impedem tempo quadrático em linhas longas e hostis.
PADROES_FIXOS: dict[str, re.Pattern] = {
    "chave-aws": re.compile(rf"{_INI}(?:AKIA|ASIA)[0-9A-Z]{{16}}{_FIM}"),
    "token-github": re.compile(rf"{_INI}(?:gh[pousr]_[A-Za-z0-9]{{36,255}}|github_pat_[A-Za-z0-9_]{{40,255}})"),
    "token-gitlab": re.compile(rf"{_INI}glpat-[A-Za-z0-9_-]{{20,100}}"),
    "chave-google": re.compile(rf"{_INI}AIza[0-9A-Za-z_-]{{35}}"),
    "chave-api-sk": re.compile(rf"{_INI}sk-[A-Za-z0-9_-]{{20,200}}"),
    "chave-stripe": re.compile(rf"{_INI}(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{{10,200}}"),
    "token-slack": re.compile(rf"{_INI}xox[abprs]-[A-Za-z0-9-]{{10,200}}"),
    "jwt": re.compile(rf"{_INI}eyJ[A-Za-z0-9_-]{{8,300}}\.eyJ[A-Za-z0-9_-]{{8,2000}}\.[A-Za-z0-9_-]{{8,600}}"),
    "chave-privada": re.compile(r"-----BEGIN (?:[A-Z]{1,20} ){0,4}PRIVATE KEY-----"),
    "credencial-em-url": re.compile(rf"{_INI}[A-Za-z][A-Za-z0-9+.-]{{0,30}}://[^\s/:@]{{1,100}}:[^\s/@]{{1,200}}@"),
}
PADROES: dict[str, re.Pattern] = {
    **PADROES_FIXOS,
    # nome com cara de segredo (também dentro de outro: aws_secret_access_key, DB_PASSWORD),
    # separador (=, :, =>, célula de tabela, "é") e valor (entre aspas/crases, ou palavra longa)
    # também ancorado no início do token ([\w.-]): uma tentativa por palavra, não uma por ponto/hífen
    # até 80 caracteres antes do nome (config.servico.banco.password) e 40 depois; com o valor de até
    # 202, o maior casamento fica abaixo de SOBREPOSICAO
    "senha-atribuida": re.compile(rf"(?i)(?<![\w.-])[\w.-]{{0,80}}?{_NOME}[\w.-]{{0,40}}?{_SEPARADOR}{_VALOR}"),
    # começa só no início do token (não depois de cada ponto): uma tentativa por palavra, linear
    "email": re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,255}\.[A-Za-z]{2,24}"),
}

# Conteúdo que plugins conhecidos do Obsidian executam sozinhos (bloqueante) ou que só roda com
# clique (aviso). A cerca pode estar dentro de citação/callout (`>`, `> >`) e de item de lista.
_CERCA = r"^[ \t>]*(?:(?:[-*+]|\d{1,9}[.)])[ \t]+)?(?:`{3,}|~{3,})[ \t]*"
EXECUTAVEL: dict[str, re.Pattern] = {
    "bloco-executavel": re.compile(_CERCA + r"(?:dataviewjs|js-engine|meta-bind-js-view|run-[\w-]{1,30}|button"
                                   r"|templater[\w-]{0,20})\b", re.IGNORECASE),
    "dataview-js-inline": re.compile(r"`[ \t]*\$="),
    "templater": re.compile(r"<%"),
}
SHELL = re.compile(_CERCA + r"(?:sh|bash|zsh|fish|shell|console|powershell|pwsh|ps1|cmd|bat)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Achado:
    arquivo: str
    linha: int
    tipo: str
    trecho: str            # mascarado
    bloqueia: bool = True  # False = só aviso (ex.: linha longa demais, não varrida)

    def __str__(self) -> str:
        return f"{self.arquivo}:{self.linha}: {self.tipo}: {self.trecho}" + ("" if self.bloqueia else " (aviso)")


def mascarar(s: str) -> str:
    return s[:4] + "…" if len(s) > 6 else "…"


def carregar_termos(caminho: Path | None) -> list[re.Pattern]:
    """Uma regex por linha (sem diferenciar maiúsculas); linhas vazias e `#` são ignoradas."""
    if not caminho:
        return []
    termos = []
    for n, linha in enumerate(caminho.read_text(encoding="utf-8").splitlines(), 1):
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        try:
            termos.append(re.compile(linha, re.IGNORECASE))
        except re.error as e:
            raise ValueError(f"{caminho.name}:{n}: regex inválida ({e})") from None
    return termos


def _email_permitido(email: str, permitidos: tuple[str, ...]) -> bool:
    email = email.lower()
    return any(email == p.lower() or (p.startswith("@") and email.endswith(p.lower())) for p in permitidos)


def _parece_segredo(valor: str, separador: str) -> bool:
    """Filtra prosa ("a senha é armazenada no keyring", "token: nenhum"). Valor entre aspas ou
    crases sempre conta. Sem aspas: não pode ser nome de variável nem palavra comum; depois de
    `=`/`=>` (atribuição) basta isso; depois de `:`, `|` ou "é" precisa ter dígito ou símbolo."""
    if valor[0] in "\"'`":
        return True
    if _NOME_DE_VARIAVEL.fullmatch(valor) or valor.lower().strip(".,;") in _PALAVRAS_COMUNS:
        return False
    if separador.strip() in ("=", "=>"):
        return True
    return any(not c.isalpha() for c in valor)


def bloqueantes(achados: list[Achado]) -> list[Achado]:
    return [a for a in achados if a.bloqueia]


def varrer_texto(texto: str, nome: str = "-", termos: list[re.Pattern] | None = None,
                 emails_permitidos: tuple[str, ...] = (), executavel: bool = True) -> list[Achado]:
    achados = []
    for n, linha in enumerate(texto.splitlines(), 1):
        if executavel:
            for tipo, rx in EXECUTAVEL.items():
                if m := rx.search(linha):  # padrões ancorados ou literais: lineares
                    achados.append(Achado(nome, n, tipo, mascarar(m.group(0).strip())))
            if SHELL.search(linha):
                achados.append(Achado(nome, n, "bloco-de-shell", mascarar(linha.strip()), bloqueia=False))
        for tipo, rx in PADROES_FIXOS.items():
            achados += [Achado(nome, n, tipo, mascarar(m.group(0))) for m in rx.finditer(linha)]
        aceitos: set[tuple[str, int]] = set()  # (tipo, início) só de casamentos aceitos
        for inicio, trecho in _janelas(linha):
            primeira, ultima = inicio == 0, inicio + len(trecho) >= len(linha)
            for tipo, rx in [*((t, PADROES[t]) for t in ("senha-atribuida", "email")),
                             *(("termo-proibido", rx) for rx in termos or [])]:
                for m in rx.finditer(trecho):
                    # casamento que encosta na borda de uma janela pode estar cortado (senha pela
                    # metade, e-mail com o domínio truncado num domínio permitido). A sobreposição
                    # é maior que o maior casamento possível, então a versão inteira está na janela
                    # vizinha: aqui ele é ignorado, e não marcado como visto.
                    if (not ultima and m.end() == len(trecho)) or (not primeira and m.start() == 0):
                        continue
                    chave = (tipo, inicio + m.start())
                    if chave in aceitos:
                        continue
                    if tipo == "email" and _email_permitido(m.group(0), emails_permitidos):
                        continue
                    if tipo == "senha-atribuida" and not _parece_segredo(m.group("valor"), m.group("sep")):
                        continue
                    aceitos.add(chave)
                    achados.append(Achado(nome, n, tipo, mascarar(m.group(0))))
    return achados


def _janelas(linha: str):
    """Janelas de JANELA caracteres; cada uma começa SOBREPOSICAO antes do fim da anterior."""
    if len(linha) <= JANELA:
        yield 0, linha
        return
    passo = JANELA - SOBREPOSICAO
    for inicio in range(0, len(linha) - SOBREPOSICAO, passo):
        yield inicio, linha[inicio:inicio + JANELA]


_ABRE_CERCA = re.compile(r"^[ \t>]*(?:(?:[-*+]|\d{1,9}[.)])[ \t]+)?(`{3,}|~{3,})")
_FECHA_CERCA = re.compile(r"^[ \t>]*(?:(?:[-*+]|\d{1,9}[.)])[ \t]+)?(`{3,}|~{3,})[ \t]*$")
_INLINE_JS = re.compile(r"`[ \t]*\$=[^`\n]{0,2000}`?")


def _hash(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8", "replace")).hexdigest()


def regioes_executaveis(texto: str) -> collections.Counter:
    """Multiconjunto de (tipo, hash) de cada região executável: um bloco cercado inteiro (da cerca
    de abertura à de fechamento), cada `<% … %>` e cada inline `$=…`. Comparar o de antes com o de
    depois diz se a sessão criou ou alterou código executável, e não só se mudou a contagem."""
    regioes: collections.Counter = collections.Counter()
    linhas = texto.splitlines()
    i = 0
    while i < len(linhas):
        if not EXECUTAVEL["bloco-executavel"].search(linhas[i]):
            i += 1
            continue
        cerca = _ABRE_CERCA.match(linhas[i]).group(1)
        j = i + 1
        while j < len(linhas):
            fecha = _FECHA_CERCA.match(linhas[j])
            if fecha and fecha.group(1)[0] == cerca[0] and len(fecha.group(1)) >= len(cerca):
                break
            j += 1
        regioes[("bloco-executavel", _hash("\n".join(linhas[i:j + 1])))] += 1
        i = j + 1
    # `<% … %>`; sem fechamento, a região vai até o fim da linha. As buscas só andam para a frente
    # (o próximo `%>` é guardado e só procurado de novo quando fica para trás): linear.
    pos, fecha = texto.find("<%"), -2
    while pos != -1:
        if fecha != -1 and fecha < pos + 2:
            fecha = texto.find("%>", pos + 2)
        if fecha != -1:
            fim = fecha + 2
        else:
            fim = texto.find("\n", pos)
            fim = len(texto) if fim == -1 else fim
        regioes[("templater", _hash(texto[pos:fim]))] += 1
        pos = texto.find("<%", fim)
    for m in _INLINE_JS.finditer(texto):
        regioes[("dataview-js-inline", _hash(m.group(0)))] += 1
    return regioes


def rebaixar_preexistentes(depois: list[Achado], antes: list[Achado], texto_depois: str = "",
                           texto_antes: str = "") -> list[Achado]:
    """Separa o que a sessão automática acrescentou do que já estava na nota (é da pessoa).

    - Tipos executáveis: compara as regiões executáveis por conteúdo (hash). Região nova ou com o
      corpo alterado bloqueia; região idêntica à de antes vira aviso; região removida não conta.
    - Demais tipos: compara a contagem por tipo; se não aumentou, vira aviso."""
    novas = regioes_executaveis(texto_depois) - regioes_executaveis(texto_antes)
    executaveis_novos = {tipo for tipo, _ in novas}
    ja_havia = collections.Counter(a.tipo for a in bloqueantes(antes))
    agora = collections.Counter(a.tipo for a in bloqueantes(depois))

    def preexistente(a: Achado) -> bool:
        if a.tipo in EXECUTAVEL:
            return a.tipo not in executaveis_novos
        return agora[a.tipo] <= ja_havia[a.tipo]

    return [dataclasses.replace(a, tipo=f"{a.tipo} (preexistente)", bloqueia=False)
            if a.bloqueia and preexistente(a) else a for a in depois]


def varrer_arquivos(arquivos, termos: list[re.Pattern] | None = None, emails_permitidos: tuple[str, ...] = (),
                    anteriores: dict[str, str] | None = None) -> list[Achado]:
    """Varre os arquivos. `anteriores` (caminho → texto antes da sessão automática) faz só os achados
    novos bloquearem; arquivo ausente do dicionário é tratado como novo (tudo conta)."""
    achados = []
    for arq in arquivos:
        p = Path(arq)
        if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".pdf") or not p.is_file():
            continue
        texto = p.read_text(encoding="utf-8", errors="replace")
        # conteúdo executável só importa em nota (.md); em outro texto, só segredos
        nota = p.suffix.lower() == ".md"
        deste = varrer_texto(texto, str(arq), termos, emails_permitidos, executavel=nota)
        if anteriores is not None and str(p) in anteriores:
            antes = varrer_texto(anteriores[str(p)], str(arq), termos, emails_permitidos, executavel=nota)
            deste = rebaixar_preexistentes(deste, antes, texto, anteriores[str(p)] if nota else "")
        achados += deste
    return achados


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("arquivos", nargs="+", type=Path)
    ap.add_argument("--termos", type=Path, help="arquivo com termos proibidos (fora do repositório)")
    ap.add_argument("--permitir-email", action="append", default=[], metavar="EMAIL_OU_@DOMINIO")
    a = ap.parse_args(argv)
    try:
        termos = carregar_termos(a.termos)
        achados = varrer_arquivos(a.arquivos, termos, tuple(a.permitir_email))
    except (OSError, ValueError) as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    for x in achados:
        print(x)
    print(f"{len(bloqueantes(achados))} achado(s) e {len(achados) - len(bloqueantes(achados))} aviso(s) "
          f"em {len(a.arquivos)} arquivo(s)", file=sys.stderr)
    return 1 if bloqueantes(achados) else 0


if __name__ == "__main__":
    sys.exit(main())
