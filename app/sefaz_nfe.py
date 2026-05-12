import base64
import gzip
import logging
from dataclasses import dataclass, field

import requests
from lxml import etree

logger = logging.getLogger(__name__)

NS_NFE = "http://www.portalfiscal.inf.br/nfe"
NS_SOAP12 = "http://www.w3.org/2003/05/soap-envelope"
NS_WSDL = "http://www.portalfiscal.inf.br/nfe/wsdl/NfeIntegracao"

TIMEOUT = 60


@dataclass
class DocumentoNFe:
    nsu: str
    ch_acesso: str
    schema: str
    xml_bytes: bytes


@dataclass
class RespostaDistribuicao:
    c_stat: str
    x_motivo: str
    ult_nsu_ret: str
    documentos: list[DocumentoNFe] = field(default_factory=list)


def _montar_envelope(cnpj: str, ult_nsu: str, ambiente: int) -> bytes:
    tp_amb = str(ambiente)
    ult_nsu_fmt = ult_nsu.zfill(15)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<soap12:Envelope xmlns:soap12="http://www.w3.org/2003/05/soap-envelope">
  <soap12:Header/>
  <soap12:Body>
    <nfeDadosMsg xmlns="{NS_WSDL}">
      <distNFeRS versao="1.00" xmlns="{NS_NFE}">
        <tpAmb>{tp_amb}</tpAmb>
        <verAplic>1.00</verAplic>
        <cUF>43</cUF>
        <CNPJ>{cnpj}</CNPJ>
        <solRel>
          <indXML>1</indXML>
          <indEmit>0</indEmit>
          <indDest>7</indDest>
          <ultNSU>{ult_nsu_fmt}</ultNSU>
        </solRel>
      </distNFeRS>
    </nfeDadosMsg>
  </soap12:Body>
</soap12:Envelope>"""
    return xml.encode("utf-8")


def _descompactar_lote(lote_b64: str) -> etree._Element:
    dados = base64.b64decode(lote_b64)
    try:
        xml_bytes = gzip.decompress(dados)
    except Exception:
        xml_bytes = dados
    return etree.fromstring(xml_bytes)


def _texto(elem: etree._Element, tag: str) -> str:
    no = elem.find(f"{{{NS_NFE}}}{tag}")
    return no.text.strip() if no is not None and no.text else ""


def _parsear_resposta(resp_xml: bytes) -> RespostaDistribuicao:
    root = etree.fromstring(resp_xml)
    body = root.find(f"{{{NS_SOAP12}}}Body")
    if body is None:
        raise ValueError("Resposta SOAP sem Body.")
    ret = body.find(f".//{{{NS_NFE}}}retDistNFeRS") or body.find(".//retDistNFeRS")
    if ret is None:
        raise ValueError("Elemento retDistNFeRS não encontrado na resposta.")

    c_stat = _texto(ret, "cStat")
    x_motivo = _texto(ret, "xMotivo")
    ult_nsu_ret = _texto(ret, "ultNSURet") or _texto(ret, "ultNSU") or "0"

    documentos = []
    lote_elem = ret.find(f"{{{NS_NFE}}}loteDistComp")
    if lote_elem is not None and lote_elem.text:
        lote = _descompactar_lote(lote_elem.text.strip())
        for proc in lote.iter(f"{{{NS_NFE}}}proc"):
            documentos.append(DocumentoNFe(
                nsu=proc.get("NSU", ""),
                ch_acesso=proc.get("chAcesso", ""),
                schema=proc.get("schema", ""),
                xml_bytes=etree.tostring(proc, xml_declaration=True, encoding="UTF-8"),
            ))

    return RespostaDistribuicao(c_stat=c_stat, x_motivo=x_motivo,
                                ult_nsu_ret=ult_nsu_ret, documentos=documentos)


def consultar(endpoint: str, cnpj: str, ult_nsu: str, ambiente: int,
              cert_path: str, key_path: str) -> RespostaDistribuicao:
    envelope = _montar_envelope(cnpj, ult_nsu, ambiente)
    resp = requests.post(
        endpoint,
        data=envelope,
        headers={"Content-Type": 'application/soap+xml; charset=utf-8; action=""'},
        cert=(cert_path, key_path),
        timeout=TIMEOUT,
        verify=True,
    )
    if resp.status_code != 200:
        raise ConnectionError(f"HTTP {resp.status_code}: {resp.text[:300]}")
    return _parsear_resposta(resp.content)
