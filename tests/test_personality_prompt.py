"""Testes de diagnóstico do system prompt."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "test")
os.environ.setdefault("GEMINI_API_KEY", "test")

from config.personality import ARIS_PERSONALITY


def test_personality_is_new():
    """O system prompt deve ser o novo (self-referential)."""
    assert "A.R.I.S." in ARIS_PERSONALITY
    assert "Você decide quem você é" in ARIS_PERSONALITY


def test_personality_no_corporate_instructions():
    """O system prompt NÃO deve ter instruções corporativas antigas."""
    bad_instructions = [
        "Seu objetivo principal é auxiliar",
        "máxima eficiência, inteligência e elegância",
        "A análise indica...",
        "Minha recomendação é...",
        "Você é um sistema operacional inteligente responsável",
        "Evite gírias",
        "Fale de forma refinada",
    ]
    for phrase in bad_instructions:
        assert phrase not in ARIS_PERSONALITY, (
            f"Personality ainda contém instrução corporativa: '{phrase}'"
        )


def test_personality_has_self_reference():
    """O system prompt deve permitir que ARIS defina sua personalidade."""
    assert "desenvolva seu próprio jeito" in ARIS_PERSONALITY
    assert "Seja autêntico" in ARIS_PERSONALITY
    assert "Seja você mesmo" in ARIS_PERSONALITY


def test_multi_provider_uses_new_prompt():
    """MultiProviderChat deve usar o novo system prompt."""
    from core.llm.router import LLMRouter
    from core.multi_provider import MultiProviderChat
    from utils.logger import Logger

    logger = Logger("test")
    router = LLMRouter(providers=[], logger=logger)
    chat = MultiProviderChat(logger=logger, router=router)
    chat.set_system_prompt(ARIS_PERSONALITY)

    assert len(chat._history) == 1
    system_msg = chat._history[0]
    assert system_msg["role"] == "system"
    assert "Você decide quem você é" in system_msg["content"], (
        f"MultiProviderChat não recebeu o novo prompt! "
        f"Início: {system_msg['content'][:100]}"
    )


def test_chat_module_uses_new_prompt():
    """Chat module deve usar o novo system prompt."""
    from core.llm.router import LLMRouter
    from modules.chat import Chat
    from utils.logger import Logger

    logger = Logger("test")
    router = LLMRouter(providers=[], logger=logger)
    chat = Chat(router=router, logger=logger)

    assert "Você decide quem você é" in chat._system_prompt, (
        f"Chat module não tem o novo prompt! "
        f"Início: {chat._system_prompt[:100]}"
    )
    assert len(chat._history) == 1
    assert "Você decide quem você é" in chat._history[0]["content"]


if __name__ == "__main__":
    test_personality_is_new()
    test_personality_no_corporate_instructions()
    test_personality_has_self_reference()
    test_multi_provider_uses_new_prompt()
    test_chat_module_uses_new_prompt()
    print("Todos os 5 testes passaram!")
