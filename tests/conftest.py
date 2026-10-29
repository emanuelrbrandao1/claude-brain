import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "scripts"), str(RAIZ / "hooks")]

from comum import montar_config  # noqa: E402


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    (v / "analise" / "relatorios").mkdir(parents=True)
    (v / "projetos").mkdir()
    return v


@pytest.fixture
def config(tmp_path, vault):
    """Fábrica de Config apontando para pastas temporárias; aceita sobrescritas por seção."""
    def fabrica(**extra):
        codigo = tmp_path / "codigo"
        codigo.mkdir(exist_ok=True)
        bruto = {
            "raizes": [str(tmp_path)],
            "vault": str(vault),
            "timezone": "UTC",
            "log_dir": str(tmp_path / "logs"),
            "estado_dir": str(tmp_path / "estado"),
            "autosave": {"pastas": [str(codigo)]},
            "foco": {"duracao_min": 50, "virada_hora": 4, "alvo_dia_min": 100,
                     "categorias": ["leitura", "codigo"]},
            "privacidade": {"emails_permitidos": ["@exemplo.test"]},
        }
        for chave, valor in extra.items():
            if isinstance(valor, dict) and isinstance(bruto.get(chave), dict):
                bruto[chave] = {**bruto[chave], **valor}
            else:
                bruto[chave] = valor
        return montar_config(bruto, tmp_path / "config.toml")
    return fabrica
