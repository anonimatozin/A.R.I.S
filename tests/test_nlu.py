"""Testes do NLU Engine (Fase 2)."""

import pytest
from core.nlu import NLUEngine, IntentType, IntentResult


class TestNLUEngine:
    """Testes do NLUEngine."""

    def setup_method(self):
        self.nlu = NLUEngine(threshold=0.6)

    def test_search_informal(self):
        """Linguagem informal detecta SEARCH."""
        r = self.nlu.detect("mn pesquisa ai sobre python")
        assert r.intent == IntentType.SEARCH
        assert r.confidence > 0.5

    def test_search_simple(self):
        """Pesquisa simples."""
        r = self.nlu.detect("pesquisa quantos pixels tem um 4k")
        assert r.intent == IntentType.SEARCH
        assert "query" in r.params

    def test_search_question(self):
        """Pergunta = busca."""
        r = self.nlu.detect("o que é quantum computing")
        assert r.intent == IntentType.SEARCH

    def test_search_who(self):
        """Quem e = busca."""
        r = self.nlu.detect("quem é alan turing")
        assert r.intent == IntentType.SEARCH

    def test_search_where(self):
        """Onde esta = busca."""
        r = self.nlu.detect("onde fica a torre eiffel")
        assert r.intent == IntentType.SEARCH

    def test_research_aprofundada(self):
        """Pesquisa aprofundada = RESEARCH."""
        r = self.nlu.detect("faz uma pesquisa aprofundada sobre IA")
        assert r.intent == IntentType.RESEARCH
        assert r.confidence > 0.5

    def test_research_quero_saber_mais(self):
        """Quero saber mais = RESEARCH."""
        r = self.nlu.detect("quero saber mais sobre machine learning")
        assert r.intent == IntentType.RESEARCH

    def test_verify(self):
        """Verificacao detecta."""
        r = self.nlu.detect("verifica se isso é verdade")
        assert r.intent == IntentType.VERIFY
        assert r.confidence > 0.5

    def test_verify_confirma(self):
        """Confirma = verifica."""
        r = self.nlu.detect("confirma pra mim se ta certo")
        assert r.intent == IntentType.VERIFY

    def test_verify_fato(self):
        """Fact check = verifica."""
        r = self.nlu.detect("isso é verdade?")
        assert r.intent == IntentType.VERIFY

    def test_compare(self):
        """Comparacao detecta."""
        r = self.nlu.detect("compara python com javascript")
        assert r.intent == IntentType.COMPARE
        assert r.confidence > 0.5

    def test_compare_qual_melhor(self):
        """Qual melhor = comparacao."""
        r = self.nlu.detect("qual é melhor react ou vue")
        assert r.intent == IntentType.COMPARE

    def test_compare_diferenca(self):
        """Diferenca = comparacao."""
        r = self.nlu.detect("diferença entre SQL e NoSQL")
        assert r.intent == IntentType.COMPARE

    def test_latest(self):
        """Ultima noticia = LATEST."""
        r = self.nlu.detect("ultima noticia sobre eleicoes")
        assert r.intent == IntentType.LATEST
        assert r.confidence > 0.5

    def test_latest_novo(self):
        """Novo em = latest."""
        r = self.nlu.detect("o que tem de novo em tecnologia")
        assert r.intent == IntentType.LATEST

    def test_visit(self):
        """Visitar site = VISIT."""
        r = self.nlu.detect("abre o site do github")
        assert r.intent == IntentType.VISIT
        assert r.confidence > 0.5

    def test_open(self):
        """Abrir app = OPEN."""
        r = self.nlu.detect("abre o discord")
        assert r.intent == IntentType.OPEN

    def test_open_executa(self):
        """Executa = open."""
        r = self.nlu.detect("executa o chrome")
        assert r.intent == IntentType.OPEN

    def test_system_status(self):
        """Status do sistema = SYSTEM."""
        r = self.nlu.detect("como ta o sistema")
        assert r.intent == IntentType.SYSTEM

    def test_system_disk(self):
        """Disco = system."""
        r = self.nlu.detect("quanto de disco ta livre")
        assert r.intent == IntentType.SYSTEM

    def test_email(self):
        """Email detecta."""
        r = self.nlu.detect("tem email novo")
        assert r.intent == IntentType.EMAIL
        assert r.confidence > 0.5

    def test_weather(self):
        """Tempo detecta."""
        r = self.nlu.detect("qual o tempo em sao paulo")
        assert r.intent == IntentType.WEATHER
        assert r.confidence > 0.5

    def test_weather_previsao(self):
        """Previsao = weather."""
        r = self.nlu.detect("previsão do tempo pra hoje")
        assert r.intent == IntentType.WEATHER

    def test_memory(self):
        """Memoria detecta."""
        r = self.nlu.detect("lembra que eu falei sobre python ontem")
        assert r.intent == IntentType.MEMORY
        assert r.confidence > 0.5

    def test_calc(self):
        """Calculo detecta."""
        r = self.nlu.detect("quanto da 2 + 2")
        assert r.intent == IntentType.CALC
        assert r.confidence > 0.5

    def test_calc_expression(self):
        """Expressao matematica."""
        r = self.nlu.detect("calcula 15 * 3 + 7")
        assert r.intent == IntentType.CALC
        assert "expression" in r.params

    def test_translate(self):
        """Traducao detecta."""
        r = self.nlu.detect("traduz isso pra ingles")
        assert r.intent == IntentType.TRANSLATE
        assert r.confidence > 0.5

    def test_explain(self):
        """Explicacao detecta."""
        r = self.nlu.detect("explica como funciona um processador")
        assert r.intent == IntentType.EXPLAIN
        assert r.confidence > 0.5

    def test_explain_o_que_significa(self):
        """O que significa = explain."""
        r = self.nlu.detect("o que significa machine learning")
        assert r.intent == IntentType.EXPLAIN

    def test_summarize(self):
        """Resumo detecta."""
        r = self.nlu.detect("me da um resumo desse artigo")
        assert r.intent == IntentType.SUMMARIZE
        assert r.confidence > 0.5

    def test_summarize_tldr(self):
        """TLDR = summarize."""
        r = self.nlu.detect("tldr disso")
        assert r.intent == IntentType.SUMMARIZE

    def test_conversation_oi(self):
        """Oi = conversa."""
        r = self.nlu.detect("oi")
        assert r.intent == IntentType.CONVERSATION

    def test_conversation_bom_dia(self):
        """Bom dia = conversa."""
        r = self.nlu.detect("bom dia")
        assert r.intent == IntentType.CONVERSATION

    def test_conversation_obrigado(self):
        """Obrigado = conversa."""
        r = self.nlu.detect("obrigado")
        assert r.intent == IntentType.CONVERSATION

    def test_conversation_tchau(self):
        """Tchau = conversa."""
        r = self.nlu.detect("tchau, ate mais")
        assert r.intent == IntentType.CONVERSATION

    def test_unknown(self):
        """Texto sem padrao = unknown."""
        r = self.nlu.detect("asdfghjkl")
        assert r.intent == IntentType.UNKNOWN

    def test_confidence_below_threshold(self):
        """Confidence baixa indica LLM needed."""
        r = self.nlu.detect("asdfghjkl")
        assert self.nlu.should_use_llm(r) is True

    def test_confidence_above_threshold(self):
        """Confidence alta nao precisa de LLM."""
        r = self.nlu.detect("pesquisa python")
        assert self.nlu.should_use_llm(r) is False

    def test_alternatives(self):
        """Alternativas sao retornadas."""
        r = self.nlu.detect("pesquisa e compara python com java")
        # Pelo menos uma das duas intencoes deve aparecer
        assert r.intent in (IntentType.SEARCH, IntentType.COMPARE)

    def test_params_query(self):
        """Query extraida corretamente."""
        r = self.nlu.detect("pesquisa quantos pixels tem 4k")
        assert "query" in r.params
        assert "4k" in r.params["query"]

    def test_params_compare_items(self):
        """Items de comparacao extraidos."""
        r = self.nlu.detect("compara python com javascript")
        assert "items" in r.params
        assert len(r.params["items"]) == 2

    def test_params_weather_city(self):
        """Cidade extraida pra weather."""
        r = self.nlu.detect("tempo em rio de janeiro")
        assert "city" in r.params

    def test_normalize(self):
        """Normalizacao funciona."""
        r = self.nlu.detect("PESQUISA SOBRE PYTHON")
        assert r.intent == IntentType.SEARCH

    def test_raw_text_preserved(self):
        """Texto original preservado."""
        original = "mn pesquisa ai por favor"
        r = self.nlu.detect(original)
        assert r.raw_text == original
