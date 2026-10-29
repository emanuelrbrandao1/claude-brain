import os
import ssl
from unittest import mock

import pytest

import enviar_email
from comum import Email

PNG = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def relatorio(tmp_path):
    pasta = tmp_path / "relatorios"
    (pasta / "img").mkdir(parents=True)
    (pasta / "img" / "ok.png").write_bytes(PNG)
    (tmp_path / "fora.png").write_bytes(PNG)
    os.symlink(tmp_path / "fora.png", pasta / "img" / "atalho.png")

    def escrever(corpo: str):
        arq = pasta / "r.md"
        arq.write_text(f"---\ntipo: relatorio\n---\n# Semana\n\n{corpo}\n", encoding="utf-8")
        return enviar_email.montar(arq, Email(usuario="a@exemplo.test"))
    return escrever


def test_html_cru_vira_texto(relatorio):
    _, imagens, html = relatorio('<img src=http://rastreador.test/x.png>\n\n'
                                 '<script>alert(1)</script>\n\nok <b onclick="x">b</b>')
    assert "<img" not in html and "<script" not in html and "<b " not in html
    assert "&lt;img src=http://rastreador.test/x.png&gt;" in html
    assert imagens == []


def test_imagem_remota_em_markdown_e_omitida(relatorio):
    _, imagens, html = relatorio("![grafico](https://rastreador.test/p.png)")
    assert "rastreador.test" not in html and imagens == []
    assert "[imagem omitida: grafico]" in html


@pytest.mark.parametrize("src", ["../fora.png", "img/atalho.png", "img/nao-existe.png", "/etc/hostname"])
def test_imagem_fora_da_pasta_nao_e_anexada(relatorio, src):
    msg, imagens, html = relatorio(f"![x]({src})")
    assert imagens == []
    assert "cid:" not in html
    assert len(list(msg.iter_attachments())) == 0


def test_imagem_local_vai_por_cid(relatorio):
    msg, imagens, html = relatorio("![ok](img/ok.png)\n\n![[img/ok.png]]")
    assert [c for c, _ in imagens] == ["img0", "img1"]
    assert 'src="cid:img0"' in html and 'src="cid:img1"' in html
    relacionadas = [p for p in msg.walk() if p.get("Content-ID")]
    assert {p["Content-ID"] for p in relacionadas} == {"<img0>", "<img1>"}


def test_links_viram_texto_sem_href(relatorio):
    _, _, html = relatorio("[a](javascript:alert(1)) [b](https://rastreador.test/?d=dado) [[Nota|texto]]")
    assert "href" not in html and "<a" not in html
    assert "<span>b</span> (https://rastreador.test/?d=dado)" in html  # URL visível, não clicável
    assert "texto" in html and "[[" not in html


def test_dominio_da_lista_mantem_link(tmp_path):
    arq = tmp_path / "r.md"
    arq.write_text("# R\n\n[doc](https://docs.exemplo.test/x) [fora](https://outro.test/x)\n")
    _, _, html = enviar_email.montar(arq, Email(dominios_link=("exemplo.test",)))
    assert 'href="https://docs.exemplo.test/x"' in html and 'href="https://outro.test/x"' not in html


def test_smtps_usa_contexto_tls_verificado():
    cfg = Email(host="smtp.exemplo.test", porta=465, seguranca="ssl", usuario="a@exemplo.test")
    with mock.patch("smtplib.SMTP_SSL") as smtp:
        enviar_email.enviar(mock.Mock(), cfg, "x")
    contexto = smtp.call_args.kwargs["context"]
    assert isinstance(contexto, ssl.SSLContext)
    assert contexto.verify_mode == ssl.CERT_REQUIRED and contexto.check_hostname


def test_starttls_usa_contexto_tls_verificado():
    cfg = Email(host="smtp.exemplo.test", porta=587, seguranca="starttls", usuario="a@exemplo.test")
    with mock.patch("smtplib.SMTP") as smtp:
        enviar_email.enviar(mock.Mock(), cfg, "x")
    conexao = smtp.return_value.__enter__.return_value
    contexto = conexao.starttls.call_args.kwargs["context"]
    assert contexto.verify_mode == ssl.CERT_REQUIRED


def test_senha_de_arquivo_exige_0600(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_BRAIN_SMTP_SENHA", raising=False)
    arq = tmp_path / "senha"
    arq.write_text("segredo-de-teste\n")
    arq.chmod(0o644)
    cfg = Email(senha_arquivo=str(arq))
    with pytest.raises(enviar_email.ErroEmail, match="0600"):
        enviar_email.ler_senha(cfg)
    arq.chmod(0o600)
    assert enviar_email.ler_senha(cfg) == "segredo-de-teste"


def test_senha_do_ambiente_tem_prioridade(monkeypatch):
    monkeypatch.setenv("CLAUDE_BRAIN_SMTP_SENHA", "do-ambiente")
    assert enviar_email.ler_senha(Email(senha_arquivo="/nao/existe")) == "do-ambiente"
