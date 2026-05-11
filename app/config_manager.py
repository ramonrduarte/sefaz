import json
import os
from pathlib import Path
from cryptography.fernet import Fernet

DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

CONFIG_FILE = DATA_DIR / "config.json"
KEY_FILE = DATA_DIR / "config.key"
CERT_FILE = DATA_DIR / "certificado.pfx"

_CONFIG_PADRAO = {
    "cnpj": "",
    "pasta_destino": "/notas",
    "ambiente": 1,
    "certificado": {
        "caminho": "",
        "senha_criptografada": ""
    },
    "nsu": {
        "nfe": "0",
        "cte": "0"
    },
    "endpoints": {
        "nfe_producao": "https://www.sefaz.rs.gov.br/ws/NfeDistribuicaoDFe/NfeDistribuicaoDFeRSContabilista.asmx",
        "nfe_homologacao": "https://www.sefaz.rs.gov.br/ws-hom/NfeDistribuicaoDFe/NfeDistribuicaoDFeRSContabilista.asmx",
        "cte_producao": "https://www.sefaz.rs.gov.br/ws/CTeDistribuicaoDFe/CTeDistribuicaoDFeRSContabilista.asmx",
        "cte_homologacao": "https://www.sefaz.rs.gov.br/ws-hom/CTeDistribuicaoDFe/CTeDistribuicaoDFeRSContabilista.asmx"
    }
}


def _obter_fernet() -> Fernet:
    if not KEY_FILE.exists():
        KEY_FILE.write_bytes(Fernet.generate_key())
    return Fernet(KEY_FILE.read_bytes())


def carregar() -> dict:
    if not CONFIG_FILE.exists():
        return dict(_CONFIG_PADRAO)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        dados = json.load(f)
    for chave, valor in _CONFIG_PADRAO.items():
        if chave not in dados:
            dados[chave] = valor
    return dados


def salvar(config: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def criptografar_senha(senha: str) -> str:
    return _obter_fernet().encrypt(senha.encode()).decode()


def descriptografar_senha(senha_criptografada: str) -> str:
    return _obter_fernet().decrypt(senha_criptografada.encode()).decode()


def obter_senha_certificado(config: dict) -> str:
    return descriptografar_senha(config["certificado"]["senha_criptografada"])


def atualizar_nsu(tipo: str, nsu: str) -> None:
    config = carregar()
    config["nsu"][tipo] = nsu
    salvar(config)


def obter_endpoint(config: dict, tipo: str) -> str:
    amb = "producao" if config.get("ambiente", 1) == 1 else "homologacao"
    return config["endpoints"][f"{tipo}_{amb}"]


def esta_configurado(config: dict) -> tuple[bool, list[str]]:
    erros = []
    if not config.get("cnpj"):
        erros.append("CNPJ não configurado")
    if not config.get("pasta_destino"):
        erros.append("Pasta de destino não configurada")
    if not config["certificado"].get("caminho"):
        erros.append("Certificado não configurado")
    if not config["certificado"].get("senha_criptografada"):
        erros.append("Senha do certificado não configurada")
    return len(erros) == 0, erros
