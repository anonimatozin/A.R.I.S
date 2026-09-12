# Prompt para Claude — Análise do ARIS Atualizado

Cole este prompt no Claude e peça para ele analisar e sugerir melhorias:

---

## Contexto

Sou o desenvolvedor do A.R.I.S., um assistente pessoal via terminal em Python 3.12 (Windows). Acabei de implementar 5 features estruturais e quero que você analise o que foi feito e sugira O QUE MAIS FAZER — tudo de uma vez, sem perguntas, sem etapas. Lista completa.

## O que foi implementado

### 1. Command Registry (substituiu monolito de 400 linhas)
- `core/commands.py`: `CommandRegistry` com decorators `@registry.register_intent()`
- `core/handlers.py`: 22 handlers migrados (weather, desktop, scheduler, etc)
- `core/aris.py`: `_execute_intent()` reduzido de ~400 para ~20 linhas
- Cada handler recebe `action`, `params`, `**ctx` (instâncias dos módulos)
- Novo módulo = novo arquivo em `plugins/`, zero edição em aris.py

### 2. Plugin System
- `core/module_manager.py`: Auto-load de `plugins/*.py` + `modules/*.py`
- Plugins podem ter `register(registry)` para auto-registro
- `plugins/calculator.py`: Exemplo funcional (eval de expressões)
- Conflito módulo/plugin detectado automaticamente

### 3. Safety Real
- `CommandRegistry.execute_intent()` verifica safety antes de executar
- 23 mapeamentos: 12 SAFE, 11 CAUTION, 1 CRITICAL (exit)
- CRITICAL bloqueia até confirmação + senha
- Audit log em `data/safety_audit.json`
- Safety conectado via `registry.set_safety(self._safety)`

### 4. Rate Limiter
- `core/rate_limiter.py`: Classe `RateLimiter` com janela deslizante
- 4 limiters: Groq (30/min), SerpAPI (5/min), Gemini (60/min), Ollama (20/min)
- Integrado em `multi_provider.py`: fallback automático se limitado
- Integrado em `hyper_search.py`: aviso se quota estourada

### 5. Knowledge Graph Persistência
- Já existia: `_load()`/`save()` em `data/knowledge_graph.json`
- Entidades, relações, fatos persistem entre sessões

## Arquitetura atual
```
ARIS/
├── core/
│   ├── aris.py          # Orquestrador (418 linhas)
│   ├── commands.py        # Registry + safety hook
│   ├── handlers.py        # 22 intent handlers
│   ├── advanced_interpreter.py  # NLU multi-comando
│   ├── multi_provider.py  # Groq/Gemini/Ollama + rate limiting
│   ├── rate_limiter.py    # Rate limiter genérico
│   ├── memory.py          # CRUD memória
│   ├── memory_models.py   # Modelos
│   ├── memory_organizer.py # Auto-limpeza
│   ├── module_manager.py  # Auto-load modules + plugins
│   └── intent.py          # Intent analyzer legado
├── modules/               # 16 módulos internos
├── plugins/               # Plugins externos (auto-load)
├── config/
├── utils/
├── system/
├── weather/
└── search/
```

## APIs disponíveis
- GROQ_API_KEY (chat primário)
- OPENWEATHER_API_KEY + WEATHERAPI_KEY (clima)
- SERPAPI_KEY (busca web)
- Ollama local (fallback)
- Playwright (browser automation, async não integrado)

## O que NÃO fazer (anti-padrões)
1. Não criar GUI agora
2. Não adicionar dependências sem necessidade
3. Não fazer refatoração massiva
4. Não ignorar base existente
5. Não adicionar features sem testes
6. Não copiar de referências
7. Não quebrar compatibilidade
8. Não usar APIs sem fallback
9. Não deixar módulos sem integração
10. Não esquecer do prompt-mestre

## Sua tarefa

Diga TUDO de uma vez, sem perguntar nada:

1. **O que está faltando** — gaps críticos que você identifica
2. **Features novas** — ideias específicas com justificativa
3. **Melhorias de código** — refatorações pontuais (não massivas)
4. **Segurança** — o que mais proteger
5. **Performance** — otimizações concretas
6. **UX** — melhorias na experiência do terminal
7. **Integrações** — novas APIs, hardware (ESP32), serviços
8. **Testes** — o que testar e como
9. **Documentação** — o que documentar
10. **Roadmap** — ordem de implementação priorizada

Seja específico, dê exemplos de código quando possível, e justifique cada sugestão. Tudo de uma vez, nada de "posso continuar?".
