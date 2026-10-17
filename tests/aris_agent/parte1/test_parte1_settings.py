"""Testes da leitura da seção ``llm`` (Parte 1)."""

from __future__ import annotations

from aris_agent.llm.settings import (
    EXEMPLO_CADEIAS,
    ProviderConfig,
    parse_settings,
    parse_target,
)


def test_exemplo_de_cadeias_marcado_como_exemplo() -> None:
    # Os nomes do exemplo nunca podem virar padrão do código: são placeholders.
    assert set(EXEMPLO_CADEIAS) == {"easy", "normal", "hard"}
    assert all(
        "MODELO" in entry.upper()
        for entries in EXEMPLO_CADEIAS.values()
        for entry in entries
    )
    assert all(
        entry.split(":", 1)[0] in {"groq", "ollama"}
        for entries in EXEMPLO_CADEIAS.values()
        for entry in entries
    )


def test_parse_provedores_e_cadeias() -> None:
    settings = parse_settings(
        {
            "providers": {
                "groq": {
                    "base_url": "https://exemplo.test/openai/v1/",
                    "api_key_env": "GROQ_API_KEY",
                    "models": ["modelo-a", "modelo-b"],
                    "limits": {"requests_per_minute": 30, "tpm": 60000},
                    "timeout_s": 12,
                },
                "local": {
                    "base_url": "http://127.0.0.1:11434/v1",
                    "models": "modelo-local",
                },
            },
            "chains": {
                "easy": ["local:modelo-local", "groq:modelo-a"],
                "normal": ["groq:modelo-b"],
            },
            "max_wait_s": 5,
            "cooldown_s": 15,
        }
    )
    groq = settings.providers["groq"]
    assert groq.base_url == "https://exemplo.test/openai/v1"
    assert groq.api_key_env == "GROQ_API_KEY"
    assert groq.models == ("modelo-a", "modelo-b")
    assert groq.limits.requests_per_minute == 30
    assert groq.limits.tokens_per_minute == 60000
    assert groq.timeout_s == 12
    assert settings.providers["local"].models == ("modelo-local",)
    assert settings.chains["easy"] == [("local", "modelo-local"), ("groq", "modelo-a")]
    assert settings.chains["normal"] == [("groq", "modelo-b")]
    assert settings.max_wait_s == 5.0
    assert settings.cooldown_s == 15.0


def test_modelo_com_dois_pontos() -> None:
    assert parse_target("ollama:modelo:v7") == ("ollama", "modelo:v7")
    assert parse_target("groq:abc") == ("groq", "abc")
    assert parse_target("sem-modelo") is None
    assert parse_target(":x") is None
    assert parse_target("x:") is None


def test_provedor_sem_base_url_e_ignorado(caplog) -> None:
    settings = parse_settings({"providers": {"quebrado": {"models": ["m"]}}})
    assert "quebrado" not in settings.providers
    assert any("base_url" in record.message for record in caplog.records)


def test_tool_mode_desconhecido_cai_no_native(caplog) -> None:
    settings = parse_settings(
        {"providers": {"x": {"base_url": "http://x/v1", "tool_mode": "wat", "models": ["m"]}}}
    )
    assert settings.providers["x"].tool_mode == "native"
    assert any("tool_mode" in record.message for record in caplog.records)


def test_cadeia_difficulty_desconhecida_avisa(caplog) -> None:
    settings = parse_settings(
        {
            "providers": {"x": {"base_url": "http://x/v1", "models": ["m"]}},
            "chains": {"media": ["x:m"]},
        }
    )
    assert "media" in settings.chains  # guardada, mas com aviso
    assert any("difficulty desconhecida" in record.message for record in caplog.records)


def test_chain_for_fallback_e_implícita(caplog) -> None:
    settings = parse_settings(
        {
            "providers": {
                "a": {"base_url": "http://a/v1", "models": ["ma"]},
                "b": {"base_url": "http://b/v1", "models": ["mb"]},
            },
            "chains": {"normal": ["a:ma"]},
        }
    )
    assert settings.chain_for("normal") == [("a", "ma")]
    # difficulty sem cadeia cai para "normal"
    assert settings.chain_for("hard") == [("a", "ma")]

    sem_cadeias = parse_settings(
        {
            "providers": {
                "a": {"base_url": "http://a/v1", "models": ["ma"]},
                "b": {"base_url": "http://b/v1", "models": ["mb"]},
            }
        }
    )
    assert sem_cadeias.chain_for("easy") == [("a", "ma"), ("b", "mb")]
    assert any("implícita" in record.message for record in caplog.records)

    vazio = parse_settings({})
    assert vazio.chain_for("normal") == []


def test_chain_for_pula_provedor_sem_modelo() -> None:
    settings = parse_settings(
        {
            "providers": {
                "a": {"base_url": "http://a/v1", "models": ["ma"]},
                "b": {"base_url": "http://b/v1"},
            }
        }
    )
    assert settings.chain_for("normal") == [("a", "ma")]


def test_padroes_nao_fixam_modelos() -> None:
    settings = parse_settings({})
    assert settings.providers == {}
    assert settings.chains == {}
    assert ProviderConfig(name="x", base_url="http://x/v1").models == ()
