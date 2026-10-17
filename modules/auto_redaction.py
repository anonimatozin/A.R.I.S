"""Auto-Redaction - Proteção de Dados Sensíveis do A.R.I.S.

Remove automaticamente emails, tokens, senhas e dados sensíveis.
Inspirado em isair/aris.
"""

import re


class AutoRedaction:
    """Sistema de auto-redação de dados sensíveis."""

    # Padrões para detecção
    PATTERNS = {
        "email": re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
        "phone_br": re.compile(r'\b(?:\+?55\s?)?(?:\(?[1-9]{2}\)?\s?)?(?:9\s?)?[0-9]{4}[-.\s]?[0-9]{4}\b'),
        "credit_card": re.compile(r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13})\b'),
        "cpf": re.compile(r'\b[0-9]{3}\.?[0-9]{3}\.?[0-9]{3}-?[0-9]{2}\b'),
        "cnpj": re.compile(r'\b[0-9]{2}\.?[0-9]{3}\.?[0-9]{3}/?[0-9]{4}-?[0-9]{2}\b'),
        "ip_address": re.compile(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'),
        "api_key": re.compile(r'(?i)(?:api[_-]?key|apikey|token|secret|password|passwd|pwd)\s*[:=]\s*["\']?([A-Za-z0-9_\-\.]{8,})["\']?'),
        "bearer_token": re.compile(r'(?i)bearer\s+[A-Za-z0-9_\-\.]+'),
        "aws_key": re.compile(r'(?i)(?:AKIA|ASIA)[A-Z0-9]{16}'),
        "private_key": re.compile(r'-----BEGIN (?:RSA |EC )?PRIVATE KEY-----'),
        "ssn": re.compile(r'\b[0-9]{3}-[0-9]{2}-[0-9]{4}\b'),
        "ipv6": re.compile(r'\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b'),
        "mac_address": re.compile(r'\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b'),
    }

    # Mapeamento de substituição
    REPLACEMENTS = {
        "email": "[EMAIL_REDACTED]",
        "phone_br": "[TELEFONE_REDACTED]",
        "credit_card": "[CARTÃO_REDACTED]",
        "cpf": "[CPF_REDACTED]",
        "cnpj": "[CNPJ_REDACTED]",
        "ip_address": "[IP_REDACTED]",
        "api_key": "[API_KEY_REDACTED]",
        "bearer_token": "[TOKEN_REDACTED]",
        "aws_key": "[AWS_KEY_REDACTED]",
        "private_key": "[PRIVATE_KEY_REDACTED]",
        "ssn": "[SSN_REDACTED]",
        "ipv6": "[IPV6_REDACTED]",
        "mac_address": "[MAC_REDACTED]",
    }

    def __init__(self):
        self._stats = {k: 0 for k in self.PATTERNS}

    def redact(self, text: str, custom_patterns: dict | None = None) -> str:
        """Remove dados sensíveis de um texto.

        Args:
            text: Texto para redigir.
            patterns: Padrões customizados para adicionar.

        Returns:
            Texto com dados sensíveis substituídos.
        """
        if not text:
            return text

        result = text
        patterns = {**self.PATTERNS}
        if custom_patterns:
            patterns.update(custom_patterns)

        for name, pattern in patterns.items():
            matches = pattern.findall(result)
            if matches:
                self._stats[name] += len(matches)
                replacement = self.REPLACEMENTS.get(name, f"[{name.upper()}_REDACTED]")
                result = pattern.sub(replacement, result)

        return result

    def detect(self, text: str) -> list[dict]:
        """Detecta dados sensíveis sem redigir.

        Returns:
            Lista de dados encontrados.
        """
        findings = []
        for name, pattern in self.PATTERNS.items():
            matches = pattern.finditer(text)
            for match in matches:
                findings.append({
                    "type": name,
                    "value": match.group()[:20] + "..." if len(match.group()) > 20 else match.group(),
                    "start": match.start(),
                    "end": match.end(),
                })
        return findings

    def is_safe(self, text: str) -> bool:
        """Verifica se o texto contém dados sensíveis."""
        return len(self.detect(text)) == 0

    def get_stats(self) -> dict:
        """Retorna estatísticas de redação."""
        return {k: v for k, v in self._stats.items() if v > 0}

    def redact_dict(self, data: dict) -> dict:
        """Redige todos os valores string de um dicionário."""
        result = {}
        for key, value in data.items():
            if isinstance(value, str):
                result[key] = self.redact(value)
            elif isinstance(value, dict):
                result[key] = self.redact_dict(value)
            elif isinstance(value, list):
                result[key] = [
                    self.redact(v) if isinstance(v, str) else v
                    for v in value
                ]
            else:
                result[key] = value
        return result

    def redact_log(self, log_line: str) -> str:
        """Redige uma linha de log (mantém timestamp e nível)."""
        # Preservar timestamp e nível
        parts = log_line.split(" ", 2)
        if len(parts) >= 3:
            prefix = f"{parts[0]} {parts[1]}"
            content = parts[2]
            return f"{prefix} {self.redact(content)}"
        return self.redact(log_line)

    def format_report(self) -> str:
        """Gera relatório de redações realizadas."""
        stats = self.get_stats()
        total = sum(stats.values())
        lines = [
            "🔒 Auto-Redaction Report",
            f"   Total redações: {total}",
        ]
        for dtype, count in sorted(stats.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"   {dtype}: {count}")
        return "\n".join(lines)
