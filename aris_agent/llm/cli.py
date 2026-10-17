"""CLI de teste da Parte 1.

Uso::

    python -m aris_agent.llm.cli "olá"
    python -m aris_agent.llm.cli "olá" --difficulty hard
    python -m aris_agent.llm.cli "olá" --provider groq --tools-demo

Com chaves ausentes ele falha de forma limpa e explicativa (exit 2), sem
tentar rede. É um script de aplicação: escreve no stdout/stderr de propósito.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from ..config import load_config
from ..contract.errors import ProviderError
from ..contract.types import ChatMessage, Risk, ToolSpec
from ..contract.utils import redact_secrets
from .router import LLMRouter
from .settings import LLMSettings, parse_settings

PROG = "python -m aris_agent.llm.cli"

_EXEMPLO_CONFIG = """\
Exemplo de aris_agent.json (sem nomes reais de modelo — troque pelos seus):

  {
    "sections": {
      "llm": {
        "providers": {
          "groq": {
            "base_url": "https://api.groq.com/openai/v1",
            "api_key_env": "GROQ_API_KEY",
            "models": ["<MODELO-PEQUENO>"],
            "limits": {"requests_per_minute": 30, "tokens_per_day": 500000}
          },
          "ollama": {
            "base_url": "http://127.0.0.1:11434/v1",
            "models": ["<MODELO-LOCAL>"]
          }
        },
        "chains": {
          "easy": ["ollama:<MODELO-LOCAL>", "groq:<MODELO-PEQUENO>"],
          "normal": ["groq:<MODELO-MEDIO>"],
          "hard": ["groq:<MODELO-GRANDE>"]
        }
      }
    }
  }

E exporte as chaves na variável indicada em api_key_env (ex.: GROQ_API_KEY).
"""

_SISTEMA = "Você é a A.R.I.S., assistente da ARIS. Responda em português do Brasil."

_SOMA_SPEC = ToolSpec(
    name="soma",
    description="Soma dois números inteiros e devolve o resultado.",
    parameters={
        "type": "object",
        "properties": {
            "a": {"type": "integer", "description": "primeiro número"},
            "b": {"type": "integer", "description": "segundo número"},
        },
        "required": ["a", "b"],
    },
    risk=Risk.READ,
    tags=("demo",),
)


def _say(message: str = "") -> None:
    print(message)


def _utf8_streams() -> None:
    """Saída redirecionada vira UTF-8 (evita mojibake em log/pipe no Windows)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        try:
            if callable(reconfigure) and not stream.isatty():
                reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # pragma: no cover - stream já fechado
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Testa a camada de LLM da A.R.I.S. (Parte 1).",
    )
    parser.add_argument("mensagem", help="mensagem do usuário")
    parser.add_argument(
        "--difficulty",
        choices=("easy", "normal", "hard"),
        default="normal",
        help="dificuldade que escolhe a cadeia de modelos (padrão: normal)",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="restringe a cadeia a um provedor (ex.: groq)",
    )
    parser.add_argument(
        "--tools-demo",
        action="store_true",
        help="oferece uma ferramenta falsa de soma e verifica se o modelo a chama",
    )
    parser.add_argument("--config", default=None, help="caminho do aris_agent.json")
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=0.3)
    parser.add_argument(
        "--stats",
        action="store_true",
        help="imprime router.stats() em JSON ao final",
    )
    return parser


def _filter_provider(settings: LLMSettings, provider: str) -> tuple[LLMSettings | None, str | None]:
    """Restringe as cadeias a um provedor. Devolve (settings, erro)."""
    key = provider.strip().lower()
    if key not in settings.providers:
        known = ", ".join(sorted(settings.providers)) or "(nenhum)"
        return None, f"provedor desconhecido: {key}. conhecidos: {known}"
    chains = {
        difficulty: [entry for entry in entries if entry[0] == key]
        for difficulty, entries in settings.chains.items()
    }
    chains = {difficulty: entries for difficulty, entries in chains.items() if entries}
    if not chains:
        chains = {"normal": [(key, model) for model in settings.providers[key].models]}
    return replace(settings, chains=chains), None


def _describe(settings: LLMSettings, router: LLMRouter) -> list[str]:
    lines = []
    for name in sorted(settings.providers):
        config = settings.providers[name]
        reason = router.providers[name].status() if name in router.providers else "não montado"
        models = ", ".join(config.models) or "(sem modelos)"
        if reason is None:
            lines.append(f"  {name}: ativo — modelos: {models}")
        else:
            lines.append(f"  {name}: INATIVO — {reason}")
    return lines


def main(argv: list[str] | None = None) -> int:
    _utf8_streams()
    args = build_parser().parse_args(argv)

    if args.config and not Path(args.config).is_file():
        _say(f"arquivo de configuração não encontrado: {args.config}")
        return 2

    cfg = load_config(args.config)
    settings = parse_settings(cfg.section("llm"))
    if not settings.providers:
        _say("Nenhum provedor de LLM configurado.")
        _say(_EXEMPLO_CONFIG)
        return 2

    if args.provider:
        settings, error = _filter_provider(settings, args.provider)
        if error:
            _say(error)
            return 2

    router = LLMRouter(settings, data_dir=cfg.data_dir)
    try:
        for line in _describe(settings, router):
            _say(line)

        chain = settings.chain_for(args.difficulty)
        active_chain = [
            entry
            for entry in chain
            if entry[0] in router.providers and router.providers[entry[0]].status() is None
        ]
        if not chain:
            _say("Nenhuma cadeia configurada para a dificuldade pedida.")
            _say(_EXEMPLO_CONFIG)
            return 2
        if not active_chain:
            _say("")
            _say(f"Nenhum provedor ativo para difficulty={args.difficulty!r}.")
            for provider_name, model in chain:
                provider = router.providers.get(provider_name)
                reason = provider.status() if provider is not None else "não configurado"
                _say(f"  {provider_name}:{model} — {reason}")
            _say("Defina a variável de ambiente indicada acima e tente de novo.")
            return 2

        messages = [
            ChatMessage(role="system", content=_SISTEMA),
            ChatMessage(role="user", content=args.mensagem),
        ]
        tools = None
        if args.tools_demo:
            tools = [_SOMA_SPEC]
            messages.append(
                ChatMessage(
                    role="system",
                    content="Se precisar somar números, use a ferramenta `soma`.",
                )
            )

        response = router.chat(
            messages,
            tools,
            difficulty=args.difficulty,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
        )
    except ProviderError as exc:
        _say(f"erro: {redact_secrets(str(exc))}")
        return 1
    finally:
        router.close()

    message = response.message
    if message.tool_calls:
        for call in message.tool_calls:
            arguments = json.dumps(call.arguments or {}, ensure_ascii=False)
            _say(f"[chamada de ferramenta] {call.name}({arguments})")
        if message.content:
            _say(message.content)
    else:
        _say(message.content or "(sem texto)")

    total = response.usage.prompt_tokens + response.usage.completion_tokens
    _say(
        f"[{response.provider}:{response.model}] fim={response.finish_reason} "
        f"tokens={response.usage.prompt_tokens}+{response.usage.completion_tokens}={total}"
    )
    if args.stats:
        _say(json.dumps(router.stats(), ensure_ascii=False, indent=2))

    if args.tools_demo:
        if message.tool_calls:
            _say("ok: o modelo chamou a ferramenta `soma`.")
            return 0
        _say("falha: o modelo NÃO chamou a ferramenta `soma`.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
