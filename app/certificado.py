import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.serialization import pkcs12, Encoding, PrivateFormat, NoEncryption


class CertificadoInvalidoError(Exception):
    pass


class CertificadoExpiradoError(Exception):
    pass


def carregar_pfx(caminho: str, senha: str) -> tuple:
    caminho_p = Path(caminho)
    if not caminho_p.exists():
        raise CertificadoInvalidoError(f"Arquivo não encontrado: {caminho}")
    if caminho_p.suffix.lower() not in (".pfx", ".p12"):
        raise CertificadoInvalidoError("O arquivo deve ter extensão .pfx ou .p12")

    dados_pfx = caminho_p.read_bytes()
    senha_bytes = senha.encode("utf-8") if isinstance(senha, str) else senha

    try:
        chave, cert, _ = pkcs12.load_key_and_certificates(dados_pfx, senha_bytes)
    except Exception as e:
        raise CertificadoInvalidoError(f"Não foi possível abrir o certificado. Verifique a senha. ({e})")

    if cert is None:
        raise CertificadoInvalidoError("Certificado não encontrado dentro do arquivo PFX.")

    return chave, cert


def validar_certificado(caminho: str, senha: str) -> dict:
    chave, cert = carregar_pfx(caminho, senha)

    agora = datetime.now(timezone.utc)
    validade = cert.not_valid_after_utc if hasattr(cert, "not_valid_after_utc") else cert.not_valid_after.replace(tzinfo=timezone.utc)
    inicio = cert.not_valid_before_utc if hasattr(cert, "not_valid_before_utc") else cert.not_valid_before.replace(tzinfo=timezone.utc)

    if agora < inicio:
        raise CertificadoInvalidoError("O certificado ainda não é válido.")
    if agora > validade:
        raise CertificadoExpiradoError(
            f"Certificado expirado em {validade.strftime('%d/%m/%Y %H:%M')}."
        )

    dias_restantes = (validade - agora).days

    try:
        nome_cn = cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
        nome = nome_cn[0].value if nome_cn else "Desconhecido"
    except Exception:
        nome = "Desconhecido"

    return {
        "nome": nome,
        "validade": validade.strftime("%d/%m/%Y %H:%M"),
        "validade_iso": validade.isoformat(),
        "dias_restantes": dias_restantes,
        "inicio": inicio.strftime("%d/%m/%Y"),
        "serial": str(cert.serial_number),
    }


class ContextoCertificado:
    """Extrai cert+chave do PFX para arquivos PEM temporários para mTLS."""

    def __init__(self, caminho_pfx: str, senha: str):
        self._caminho = caminho_pfx
        self._senha = senha
        self._tmp_cert = None
        self._tmp_key = None

    def __enter__(self) -> tuple[str, str]:
        chave, cert = carregar_pfx(self._caminho, self._senha)

        cert_pem = cert.public_bytes(Encoding.PEM)
        key_pem = chave.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())

        self._tmp_cert = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
        self._tmp_key = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)

        self._tmp_cert.write(cert_pem)
        self._tmp_cert.flush()
        self._tmp_cert.close()

        self._tmp_key.write(key_pem)
        self._tmp_key.flush()
        self._tmp_key.close()

        return self._tmp_cert.name, self._tmp_key.name

    def __exit__(self, *args):
        for tmp in (self._tmp_cert, self._tmp_key):
            if tmp and os.path.exists(tmp.name):
                os.unlink(tmp.name)
