import logging
from pathlib import Path

from lxml import etree

logger = logging.getLogger(__name__)

_SUFIXOS = {
    "procNFe": "nfe",
    "procCancNFe": "canc",
    "procCCeNFe": "cce",
    "procEventoNFe": "evento",
    "procInutNFe": "inut",
    "procCTe": "cte",
    "procCancCTe": "canc",
    "procCCeCTe": "cce",
    "procEventoCTe": "evento",
}

_NS_NFE = "http://www.portalfiscal.inf.br/nfe"
_NS_CTE = "http://www.portalfiscal.inf.br/cte"


def _sufixo_do_schema(schema: str) -> str:
    for chave, sufixo in _SUFIXOS.items():
        if schema.startswith(chave):
            return sufixo
    return "doc"


def _extrair_data_xml(xml_bytes: bytes, tipo: str) -> tuple[str, str, str]:
    try:
        root = etree.fromstring(xml_bytes)
        ns = _NS_NFE if tipo == "NFe" else _NS_CTE
        dh_elem = root.find(f".//{{{ns}}}dhEmi") or root.find(".//dhEmi")
        if dh_elem is not None and dh_elem.text:
            partes = dh_elem.text.strip()[:10].split("-")
            if len(partes) == 3:
                return partes[0], partes[1], partes[2]
    except Exception:
        pass
    return "", "", ""


def _data_do_chave(ch_acesso: str) -> tuple[str, str]:
    if len(ch_acesso) >= 6:
        return f"20{ch_acesso[2:4]}", ch_acesso[4:6]
    return "0000", "00"


def salvar_documento(pasta_destino: str, tipo: str, ch_acesso: str,
                     schema: str, xml_bytes: bytes) -> Path:
    ano, mes, dia = _extrair_data_xml(xml_bytes, tipo)
    if not ano:
        ano, mes = _data_do_chave(ch_acesso)
        dia = "01"

    sufixo = _sufixo_do_schema(schema)
    nome_arquivo = f"{ch_acesso}-{sufixo}.xml"

    pasta = Path(pasta_destino) / tipo / ano / mes / dia
    pasta.mkdir(parents=True, exist_ok=True)

    caminho = pasta / nome_arquivo
    if caminho.exists():
        logger.debug("Arquivo já existe, ignorando: %s", caminho)
        return caminho

    caminho.write_bytes(xml_bytes)
    logger.info("Salvo: %s", caminho)
    return caminho


def verificar_pasta(pasta_destino: str) -> tuple[bool, str]:
    try:
        p = Path(pasta_destino)
        p.mkdir(parents=True, exist_ok=True)
        teste = p / ".teste_acesso"
        teste.write_text("ok")
        teste.unlink()
        return True, "Pasta acessível."
    except PermissionError:
        return False, "Sem permissão de escrita na pasta."
    except Exception as e:
        return False, f"Erro ao acessar pasta: {e}"
