"""Peças compartilhadas: configuração, validação de caminho, gravação atômica, lock e log.

Só biblioteca padrão: os hooks importam este módulo e rodam com o `python3` do sistema.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import json
import os
import tempfile
import time
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

RAIZ_REPO = Path(__file__).resolve().parent.parent
ENV_CONFIG = "CLAUDE_BRAIN_CONFIG"
DIAS = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")
# Diretórios de sistema: nunca são pasta de projeto, vault, fonte nem raiz permitida, mesmo que a
# configuração tente. Discos montados (/mnt, /media) ficam de fora por não estarem nas raízes padrão
# e porque o próprio ponto de montagem é recusado.
SISTEMA = tuple(Path(p) for p in ("/bin", "/boot", "/dev", "/etc", "/lib", "/lib32", "/lib64", "/libx32",
                                  "/opt", "/proc", "/root", "/run", "/sbin", "/srv", "/sys", "/usr",
                                  "/var", "/snap", "/System", "/Library", "/Applications"))


class ErroConfig(Exception):
    """Configuração ausente ou inválida."""


# ---------------------------------------------------------------- caminhos

def expandir(caminho: str | os.PathLike) -> Path:
    return Path(os.path.expanduser(str(caminho)))


def _real(p: str | os.PathLike) -> Path:
    return Path(os.path.realpath(p))


def _em_sistema(p: Path) -> bool:
    return any(p == s or s in p.parents for s in SISTEMA)


def validar_raiz(caminho: str | os.PathLike) -> Path:
    """Raiz sob a qual pastas configuradas e `pasta:` de notas podem ficar (padrão: a home)."""
    p = expandir(caminho)
    if not p.is_absolute() or not p.is_dir():
        raise ValueError(f"raiz precisa ser absoluta e existir: {str(caminho)!r}")
    p = _real(p)
    if len(p.parts) < 2 or _em_sistema(p):
        raise ValueError(f"raiz inaceitável (sistema ou /): {str(caminho)!r}")
    return p


def validar_pasta(caminho: str | os.PathLike, raizes: Iterable[Path] | None = None,
                  *, existir: bool = True) -> Path:
    """Caminho absoluto, específico, estritamente dentro de uma raiz permitida; senão `ValueError`.

    Usado para `pasta:` das notas e para as pastas da configuração. Um valor amplo (`/`, `~`,
    `/usr`, um disco montado) faria qualquer conversa casar com o projeto ou entrar no opt-in.
    """
    bruto = str(caminho).strip()
    if not bruto:
        raise ValueError("caminho vazio")
    p = expandir(bruto)
    if not p.is_absolute():
        raise ValueError(f"caminho não é absoluto: {bruto!r}")
    p = _real(p)
    raizes = list(raizes) if raizes is not None else [_real(Path.home())]
    if _em_sistema(p):
        raise ValueError(f"diretório de sistema: {bruto!r}")
    if not any(r in p.parents for r in raizes):
        raise ValueError(f"fora das raízes permitidas ou igual a uma delas: {bruto!r}")
    if existir and not p.is_dir():
        raise ValueError(f"pasta não existe: {bruto!r}")
    if existir and os.path.ismount(p):
        raise ValueError(f"ponto de montagem: {bruto!r}")
    return p


def dentro_de(caminho: str | os.PathLike, base: str | os.PathLike) -> bool:
    """`caminho` (resolvido, com links seguidos) fica dentro de `base` ou é a própria `base`."""
    c = os.path.realpath(caminho)
    b = os.path.realpath(base)
    return c == b or c.startswith(b.rstrip(os.sep) + os.sep)


# ---------------------------------------------------------------- arquivos

def gravar_atomico(destino: str | os.PathLike, conteudo: str | bytes, modo: int = 0o600) -> None:
    """Grava num temporário da mesma pasta e troca com `os.replace` (nunca deixa arquivo pela metade)."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    dados = conteudo.encode("utf-8") if isinstance(conteudo, str) else conteudo
    fd, tmp = tempfile.mkstemp(prefix=f".{destino.name}.", dir=destino.parent)
    try:
        os.fchmod(fd, modo)
        with os.fdopen(fd, "wb") as f:
            f.write(dados)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, destino)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def ler_json(caminho: Path, log=None) -> dict:
    """JSON de estado; ausente = {}; ilegível = {} e registra no log."""
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as e:
        if log:
            log(f"estado ilegivel {caminho.name}: {type(e).__name__}")
        return {}


def gravar_json(caminho: Path, dados: dict) -> None:
    gravar_atomico(caminho, json.dumps(dados, indent=1, ensure_ascii=False, sort_keys=True))


@contextlib.contextmanager
def trava(caminho: str | os.PathLike, espera_s: float = 0):
    """Lock exclusivo (`fcntl.flock`). Com `espera_s=0`, falha na hora se outro processo segura.

    Levanta `TimeoutError` se não conseguir no prazo.
    """
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(caminho, os.O_RDWR | os.O_CREAT, 0o600)
    limite = time.monotonic() + espera_s
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= limite:
                    raise TimeoutError(f"lock ocupado: {caminho.name}") from None
                time.sleep(0.5)
        yield
    finally:
        os.close(fd)  # fechar o descritor solta o lock


# ---------------------------------------------------------------- log

class Log:
    """Log de status: uma linha por evento, arquivo 0600, rotação simples por tamanho.

    Regra de uso: só status, códigos, contagens e nomes de arquivo. Nunca pedido, saída do
    modelo, conteúdo de nota ou de conversa.
    """

    def __init__(self, caminho: str | os.PathLike, max_bytes: int = 512 * 1024, copias: int = 3,
                 fuso: ZoneInfo | None = None):
        self.caminho = Path(caminho)
        self.max_bytes = max_bytes
        self.copias = copias
        self.fuso = fuso

    def _rodar(self) -> None:
        try:
            if self.caminho.stat().st_size < self.max_bytes:
                return
        except FileNotFoundError:
            return
        for i in range(self.copias - 1, 0, -1):
            antigo = self.caminho.with_name(f"{self.caminho.name}.{i}")
            if antigo.exists():
                os.replace(antigo, self.caminho.with_name(f"{self.caminho.name}.{i + 1}"))
        os.replace(self.caminho, self.caminho.with_name(f"{self.caminho.name}.1"))

    def __call__(self, msg: str) -> None:
        self.caminho.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._rodar()
        agora = dt.datetime.now(self.fuso) if self.fuso else dt.datetime.now().astimezone()
        linha = f"{agora:%Y-%m-%dT%H:%M:%S%z} {msg}\n"
        fd = os.open(self.caminho, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(linha)


# ---------------------------------------------------------------- configuração

@dataclass(frozen=True)
class Fonte:
    nome: str
    caminho: Path
    padrao: str = "*.md"


@dataclass(frozen=True)
class Foco:
    tabela: Path
    duracao_min: int = 50
    virada_hora: int = 4
    alvo_dia_min: tuple[int, ...] = (90,) * 7
    categorias: tuple[str, ...] = ()
    perto_dia_blocos: int = 2
    perto_pct: float = 0.10
    semanas_normal: int = 8

    @property
    def alvo_semana_min(self) -> int:
        return sum(self.alvo_dia_min)


@dataclass(frozen=True)
class Email:
    ativo: bool = False
    host: str = ""
    porta: int = 465
    seguranca: str = "ssl"  # "ssl" (SMTPS) ou "starttls"
    usuario: str = ""
    remetente: str = ""
    destino: str = ""
    senha_env: str = "CLAUDE_BRAIN_SMTP_SENHA"
    senha_arquivo: str = ""
    usar_keyring: bool = False
    prefixo_assunto: str = "[claude-brain]"
    dominios_link: tuple[str, ...] = ()  # links com href só para estes domínios; os demais viram texto


@dataclass(frozen=True)
class Config:
    arquivo: Path
    vault: Path
    log_dir: Path
    estado_dir: Path
    fuso: ZoneInfo | None
    raizes: tuple[Path, ...]
    claude_bin: str = "claude"
    modelo: str = ""
    orcamento_usd: float = 0.0
    autosave_pastas: tuple[Path, ...] = ()
    autosave_escrita: tuple[Path, ...] = ()
    autosave_ignorar: tuple[str, ...] = ()
    autosave_minimo: int = 1
    autosave_espera_s: int = 120
    autosave_tempo_max_s: int = 1800
    retomada_limite_dias: int = 30
    fontes: tuple[Fonte, ...] = ()
    analise_pasta: Path = Path("analise")
    relatorio_pasta: Path = Path("analise/relatorios")
    dia_relatorio: int = 1
    rotina_tempo_max_s: int = 1800
    rotina_commit: bool = False
    foco: Foco = field(default_factory=lambda: Foco(tabela=Path("foco.md")))
    email: Email = field(default_factory=Email)
    notificacao: str = "nenhum"
    termos_arquivo: Path | None = None
    emails_permitidos: tuple[str, ...] = ()

    def agora(self) -> dt.datetime:
        return dt.datetime.now(self.fuso) if self.fuso else dt.datetime.now().astimezone()

    def log(self, nome: str) -> Log:
        return Log(self.log_dir / f"{nome}.log", fuso=self.fuso)


def trava_do_vault(cfg: Config) -> Path:
    """Um lock só para tudo que deixa um agente escrever no vault (autosave e rotina)."""
    return cfg.estado_dir / "vault.lock"


def caminho_config(explicito: str | None = None) -> Path:
    if explicito:
        return expandir(explicito)
    if os.environ.get(ENV_CONFIG):
        return expandir(os.environ[ENV_CONFIG])
    return RAIZ_REPO / "config.toml"


SEPARADORES_DE_REGRA = set(" ,()*?[]{}\\")


def sem_separador(caminho: Path, chave: str) -> Path:
    """Caminhos que viram regra de permissão do Claude Code não podem ter espaço, vírgula nem
    sintaxe de padrão: a lista de --allowedTools é separada por espaço ou vírgula."""
    ruins = sorted(SEPARADORES_DE_REGRA & set(str(caminho)))
    if ruins:
        raise ErroConfig(f"{chave}: o caminho {str(caminho)!r} tem {''.join(ruins)!r}; renomeie (ex.: troque "
                         "espaço por hífen), porque ele entra numa regra de permissão do Claude Code")
    return caminho


def _rel_vault(vault: Path, valor: str, chave: str) -> Path:
    """Caminho relativo ao vault, sem escapar dele e sem parte oculta."""
    p = Path(valor)
    if p.is_absolute() or ".." in p.parts or any(x.startswith(".") for x in p.parts):
        raise ErroConfig(f"{chave} deve ser relativo ao vault, sem '..' e sem pasta oculta: {valor!r}")
    return vault / p


def carregar_config(explicito: str | None = None) -> Config:
    arq = caminho_config(explicito)
    try:
        with open(arq, "rb") as f:
            bruto = tomllib.load(f)
    except FileNotFoundError:
        raise ErroConfig(f"configuração não encontrada: {arq} (copie config.example.toml)") from None
    except tomllib.TOMLDecodeError as e:
        raise ErroConfig(f"configuração inválida em {arq}: {e}") from None
    return montar_config(bruto, arq)


def _pasta(valor, raizes, chave) -> Path:
    try:
        return validar_pasta(valor, raizes)
    except ValueError as e:
        raise ErroConfig(f"{chave}: {e}") from None


def montar_config(bruto: dict, arquivo: Path) -> Config:
    # a pasta do clone (skills) e a temporária (resumos) também viram regras de permissão
    sem_separador(RAIZ_REPO, "pasta do clone do claude-brain")
    sem_separador(Path(tempfile.gettempdir()), "pasta temporária (TMPDIR)")
    try:
        raizes = tuple(validar_raiz(r) for r in bruto.get("raizes", ["~"]))
    except ValueError as e:
        raise ErroConfig(f"raizes: {e}") from None
    if "vault" not in bruto:
        raise ErroConfig("falta a chave `vault`")
    vault = sem_separador(_pasta(bruto["vault"], raizes, "vault"), "vault")

    fuso = None
    if bruto.get("timezone"):
        try:
            fuso = ZoneInfo(bruto["timezone"])
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ErroConfig(f"timezone desconhecido: {bruto['timezone']!r} ({e})") from None

    auto = bruto.get("autosave", {})
    pastas = tuple(_pasta(p, raizes, "autosave.pastas") for p in auto.get("pastas", []))
    escrita = tuple(sem_separador(_rel_vault(vault, p, "autosave.escrita"), "autosave.escrita")
                    for p in auto.get("escrita", ["projetos", "conversas-avulsas", "Inicio.md"]))

    fontes = []
    for f in bruto.get("fontes", []):
        if "nome" not in f or "caminho" not in f:
            raise ErroConfig("fontes: cada fonte precisa de `nome` e `caminho`")
        caminho = sem_separador(_pasta(f["caminho"], raizes, "fontes"), "fontes")
        fontes.append(Fonte(f["nome"], caminho, f.get("padrao", "*.md")))

    fb = bruto.get("foco", {})
    alvos = fb.get("alvo_dia_min", 90)
    alvos = tuple([alvos] * 7) if isinstance(alvos, int) else tuple(alvos)
    if len(alvos) != 7 or any(not isinstance(m, int) or m < 0 for m in alvos):
        raise ErroConfig("foco.alvo_dia_min: um inteiro ou uma lista de 7 inteiros (seg..dom)")
    virada = int(fb.get("virada_hora", 4))
    if not 0 <= virada <= 12:
        raise ErroConfig("foco.virada_hora deve ficar entre 0 e 12")
    foco = Foco(
        tabela=_rel_vault(vault, fb.get("tabela", "foco/Sessoes de foco.md"), "foco.tabela"),
        duracao_min=int(fb.get("duracao_min", 50)),
        virada_hora=virada,
        alvo_dia_min=alvos,
        categorias=tuple(fb.get("categorias", ())),
        perto_dia_blocos=int(fb.get("perto_dia_blocos", 2)),
        perto_pct=float(fb.get("perto_pct", 0.10)),
        semanas_normal=int(fb.get("semanas_normal", 8)),
    )

    eb = dict(bruto.get("email", {}))
    if "dominios_link" in eb:
        eb["dominios_link"] = tuple(eb["dominios_link"])
    email = Email(**{k: eb[k] for k in Email.__dataclass_fields__ if k in eb})
    if email.seguranca not in ("ssl", "starttls"):
        raise ErroConfig("email.seguranca deve ser 'ssl' ou 'starttls'")

    rot = bruto.get("rotina", {})
    dia_rel = int(rot.get("dia_relatorio", 1))
    if not 1 <= dia_rel <= 7:
        raise ErroConfig("rotina.dia_relatorio: 1 (segunda) a 7 (domingo)")

    analise = bruto.get("analise", {})
    analise_pasta = sem_separador(_rel_vault(vault, analise.get("pasta", "analise"), "analise.pasta"),
                                  "analise.pasta")
    relatorio_pasta = _rel_vault(vault, analise.get("relatorios", "analise/relatorios"), "analise.relatorios")
    if analise_pasta not in relatorio_pasta.parents:
        raise ErroConfig("analise.relatorios precisa ficar dentro de analise.pasta")

    priv = bruto.get("privacidade", {})
    termos = expandir(priv["termos_arquivo"]) if priv.get("termos_arquivo") else None
    if termos and dentro_de(termos, RAIZ_REPO):
        raise ErroConfig("privacidade.termos_arquivo não pode ficar dentro do repositório")

    notif = bruto.get("notificacao", {}).get("backend", "nenhum")
    if notif not in ("nenhum", "auto", "notify-send", "osascript", "powershell"):
        raise ErroConfig(f"notificacao.backend desconhecido: {notif!r}")

    estado_padrao = Path(os.environ.get("XDG_STATE_HOME") or expandir("~/.local/state")) / "claude-brain"
    return Config(
        arquivo=arquivo,
        vault=vault,
        log_dir=expandir(bruto.get("log_dir") or estado_padrao / "logs"),
        estado_dir=expandir(bruto.get("estado_dir") or estado_padrao),
        fuso=fuso,
        raizes=raizes,
        claude_bin=bruto.get("claude_bin", "claude"),
        modelo=bruto.get("modelo", ""),
        orcamento_usd=float(bruto.get("orcamento_usd", 0)),
        autosave_pastas=pastas,
        autosave_escrita=escrita,
        autosave_ignorar=tuple(auto.get("ignorar_mudancas",
                                        [".obsidian/workspace.json", ".obsidian/workspace-mobile.json"])),
        autosave_minimo=int(auto.get("minimo_pedidos", 1)),
        autosave_espera_s=int(auto.get("espera_max_s", 120)),
        autosave_tempo_max_s=int(auto.get("tempo_max_s", 1800)),
        retomada_limite_dias=int(bruto.get("retomada", {}).get("limite_dias", 30)),
        fontes=tuple(fontes),
        analise_pasta=analise_pasta,
        relatorio_pasta=relatorio_pasta,
        dia_relatorio=dia_rel,
        rotina_tempo_max_s=int(rot.get("tempo_max_s", 1800)),
        rotina_commit=bool(rot.get("commit", False)),
        foco=foco,
        email=email,
        notificacao=notif,
        termos_arquivo=termos,
        emails_permitidos=tuple(priv.get("emails_permitidos", ())),
    )
