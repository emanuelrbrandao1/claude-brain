#!/usr/bin/env python3
"""Envia um relatório Markdown do vault por e-mail (SMTP com TLS verificado).

Segurança do HTML: o Markdown é convertido com HTML cru desligado (tags viram texto), links só
com http/https/mailto, e imagem só se for arquivo local dentro da pasta do relatório (depois de
resolver links simbólicos e `..`), anexada e referenciada por `cid:`. Imagem remota ou fora da
pasta vira o texto alternativo: e-mail não carrega nada de fora.

Senha: variável de ambiente (`email.senha_env`), keyring opcional, ou arquivo com permissão 0600.

Uso: enviar_email.py RELATORIO.md [--dry-run] [--config ARQ]
"""
from __future__ import annotations

import argparse
import mimetypes
import os
import re
import smtplib
import ssl
import stat
import sys
import xml.etree.ElementTree as ET
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comum import Email, ErroConfig, carregar_config, dentro_de  # noqa: E402

TIPOS_IMAGEM = {"image/png", "image/jpeg", "image/gif"}
_FRONTMATTER = re.compile(r"\A---\n.*?\n---\n", re.S)


class ErroEmail(Exception):
    pass


def _preparar_markdown(texto: str) -> str:
    """Tira o frontmatter e converte a sintaxe do Obsidian para Markdown comum."""
    texto = _FRONTMATTER.sub("", texto)
    texto = re.sub(r"!\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", r"![](\1)", texto)   # ![[img.png]] → ![](img.png)
    texto = re.sub(r"\[\[[^\]|]+\|([^\]]+)\]\]", r"\1", texto)              # [[Nota|texto]] → texto
    texto = re.sub(r"\[\[([^\]]+)\]\]", r"\1", texto)                         # [[Nota]] → Nota
    texto = re.sub(r"%%.*?%%", "", texto, flags=re.S)                         # comentários do Obsidian
    return texto


def link_permitido(href: str, dominios: tuple[str, ...]) -> bool:
    """Só http(s) para um domínio da lista (ou subdomínio dele). Lista vazia: nenhum link clicável."""
    partes = urlsplit(href)
    host = (partes.hostname or "").lower()
    return partes.scheme in ("http", "https") and any(
        host == d.lower() or host.endswith("." + d.lower()) for d in dominios)


def _conversor(base: Path, imagens: list[tuple[str, Path]], dominios: tuple[str, ...] = ()):
    """Markdown sem HTML cru e com um pós-processador que filtra imagens e links.

    Link fora da lista vira texto com a URL visível (sem href): um relatório escrito por um
    modelo poderia levar dado na URL, e o clique entregaria esse dado a terceiros."""
    import markdown
    from markdown.extensions import Extension
    from markdown.treeprocessors import Treeprocessor

    class Filtro(Treeprocessor):
        def run(self, raiz):
            pais = {filho: pai for pai in raiz.iter() for filho in pai}
            for img in list(raiz.iter("img")):
                src = img.get("src", "")
                caminho = (base / src) if src and "://" not in src and not src.startswith(("data:", "cid:")) else None
                tipo = mimetypes.guess_type(str(caminho))[0] if caminho else None
                if caminho and dentro_de(caminho, base) and caminho.is_file() and tipo in TIPOS_IMAGEM:
                    cid = f"img{len(imagens)}"
                    imagens.append((cid, Path(os.path.realpath(caminho))))
                    img.set("src", f"cid:{cid}")
                    img.set("style", "max-width:100%")
                else:  # remota, fora da pasta, inexistente ou de tipo estranho: vira texto
                    pai = pais[img]
                    texto = ET.Element("span")
                    texto.text = f"[imagem omitida: {img.get('alt') or 'sem descrição'}]"
                    texto.tail = img.tail
                    pai.insert(list(pai).index(img), texto)
                    pai.remove(img)
            for a in list(raiz.iter("a")):
                href = a.attrib.pop("href", "")
                if href and link_permitido(href, dominios):
                    a.set("href", href)
                    continue
                a.tag = "span"
                texto = "".join(a.itertext())
                if href and href != texto:
                    a.tail = f" ({href})" + (a.tail or "")

    class SemHtml(Extension):
        def extendMarkdown(self, md):
            md.preprocessors.deregister("html_block")   # bloco <div>… vira texto escapado
            md.inlinePatterns.deregister("html")        # <img …> inline vira texto escapado
            md.treeprocessors.register(Filtro(md), "filtro_de_seguranca", 0)

    return markdown.Markdown(extensions=["tables", SemHtml()])


def montar(relatorio: Path, cfg: Email) -> tuple[EmailMessage, list[tuple[str, Path]], str]:
    base = Path(os.path.realpath(relatorio.parent))
    texto = _preparar_markdown(relatorio.read_text(encoding="utf-8"))
    titulo = next((li[2:].strip() for li in texto.splitlines() if li.startswith("# ")), relatorio.stem)
    imagens: list[tuple[str, Path]] = []
    corpo = _conversor(base, imagens, cfg.dominios_link).convert(texto)
    html = ('<div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.5;'
            f'color:#0b0b0b;max-width:760px">{corpo}</div>').replace(
        "<table>", '<table style="border-collapse:collapse" cellpadding="6" border="1">')

    msg = EmailMessage()
    msg["Subject"] = f"{cfg.prefixo_assunto} {titulo}".strip()
    msg["From"] = cfg.remetente or cfg.usuario
    msg["To"] = cfg.destino or cfg.remetente or cfg.usuario
    msg.set_content(texto)
    msg.add_alternative(html, subtype="html")
    parte_html = msg.get_payload()[1]
    for cid, caminho in imagens:
        principal, sub = mimetypes.guess_type(str(caminho))[0].split("/")
        parte_html.add_related(caminho.read_bytes(), maintype=principal, subtype=sub, cid=f"<{cid}>")
    return msg, imagens, html


def ler_senha(cfg: Email) -> str:
    if cfg.senha_env and os.environ.get(cfg.senha_env):
        return os.environ[cfg.senha_env]
    if cfg.usar_keyring:
        try:
            import keyring
        except ImportError:
            raise ErroEmail("email.usar_keyring = true, mas o pacote keyring não está instalado") from None
        senha = keyring.get_password("claude-brain", cfg.usuario)
        if senha:
            return senha
    if cfg.senha_arquivo:
        p = Path(os.path.expanduser(cfg.senha_arquivo))
        st = p.stat()
        if stat.S_IMODE(st.st_mode) & 0o077 or st.st_uid != os.getuid():
            raise ErroEmail(f"{p.name}: o arquivo de senha precisa ser seu e ter permissão 0600")
        return p.read_text(encoding="utf-8").strip()
    raise ErroEmail(f"senha SMTP não encontrada (defina ${cfg.senha_env}, keyring ou senha_arquivo)")


def enviar(msg: EmailMessage, cfg: Email, senha: str) -> None:
    contexto = ssl.create_default_context()  # verifica certificado e nome do servidor
    if cfg.seguranca == "ssl":
        with smtplib.SMTP_SSL(cfg.host, cfg.porta, context=contexto, timeout=60) as s:
            s.login(cfg.usuario, senha)
            s.send_message(msg)
    else:
        with smtplib.SMTP(cfg.host, cfg.porta, timeout=60) as s:
            s.ehlo()
            s.starttls(context=contexto)
            s.ehlo()
            s.login(cfg.usuario, senha)
            s.send_message(msg)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Envia um relatório do vault por e-mail.")
    ap.add_argument("relatorio", type=Path)
    ap.add_argument("--config")
    ap.add_argument("--dry-run", action="store_true", help="monta e mostra o resumo; não lê senha nem envia")
    a = ap.parse_args(argv)
    try:
        cfg = carregar_config(a.config)
    except ErroConfig as e:
        print(f"erro de configuração: {e}", file=sys.stderr)
        return 2
    log = cfg.log("email")
    try:
        msg, imagens, html = montar(a.relatorio, cfg.email)
    except OSError as e:
        print(f"não consegui ler o relatório: {e}", file=sys.stderr)
        return 2
    if a.dry_run:
        print(f"DRY-RUN (nada enviado): assunto={msg['Subject']!r} para={msg['To']!r} "
              f"via={cfg.email.host or '(host não configurado)'}:{cfg.email.porta}/{cfg.email.seguranca} "
              f"imagens={len(imagens)} html={len(html)} caracteres")
        return 0
    if not cfg.email.ativo:
        print("e-mail desligado (email.ativo = false)", file=sys.stderr)
        return 1
    try:
        enviar(msg, cfg.email, ler_senha(cfg.email))
    except (ErroEmail, OSError, smtplib.SMTPException) as e:
        log(f"envio falhou erro={type(e).__name__}")
        print(f"envio falhou: {e}", file=sys.stderr)
        return 1
    log(f"enviado imagens={len(imagens)}")
    print(f"enviado: {msg['Subject']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
