"""Skills System - Sistema de Habilidades do A.R.I.S.

Skills são pacotes reutilizáveis de funcionalidades.
Inspirado em OpenClaw ClawHub.
"""

import json
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime


@dataclass
class Skill:
    """Uma skill/habilidade."""
    id: str
    name: str
    description: str
    category: str
    author: str = "A.R.I.S."
    version: str = "1.0.0"
    instructions: str = ""
    tools: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    tags: list[str] = field(default_factory=list)


class SkillsSystem:
    """Gerenciador de skills."""

    # Skills pré-definidas
    BUILTIN_SKILLS = [
        {
            "name": "Weather Report",
            "description": "Gera relatório completo do clima para qualquer cidade",
            "category": "weather",
            "instructions": "Use a API de clima para buscar temperatura, umidade, vento e previsão. Formate em bullet points.",
            "tools": ["weather"],
            "examples": ["Como está o clima em São Paulo?", "Vai chover amanhã?"],
            "tags": ["clima", "tempo", "previsão"],
        },
        {
            "name": "System Health Check",
            "description": "Verifica a saúde completa do sistema",
            "category": "system",
            "instructions": "Analise CPU, RAM, disco, rede e processos. Identifique gargalos e sugira otimizações.",
            "tools": ["sys"],
            "examples": ["Meu computador está lento", "Verificar sistema"],
            "tags": ["sistema", "performance", "diagnóstico"],
        },
        {
            "name": "Web Research",
            "description": "Pesquisa profunda na web com síntese",
            "category": "research",
            "instructions": "Use a pesquisa web para encontrar informações. Sintetize os resultados em um resumo claro.",
            "tools": ["websearch"],
            "examples": ["Pesquisar sobre Python", "O que émachine learning?"],
            "tags": ["pesquisa", "web", "informação"],
        },
        {
            "name": "Memory Recall",
            "description": "Busca e recupera informações salvas",
            "category": "memory",
            "instructions": "Use o sistema de memória para buscar informações relevantes. Apresente os resultados organizados.",
            "tools": ["search", "remember"],
            "examples": ["O que eu disse sobre meu projeto?", "Lembra que eu falei de Python?"],
            "tags": ["memória", "lembrar", "buscar"],
        },
        {
            "name": "Code Review",
            "description": "Revisa código e sugere melhorias",
            "category": "code",
            "instructions": "Analise o código para bugs, problemas de performance, legibilidade e boas práticas.",
            "tools": ["turbo"],
            "examples": ["Revise esse arquivo Python", "Analise meu código"],
            "tags": ["código", "review", "análise"],
        },
        {
            "name": "Productivity Tracker",
            "description": "Acompanha produtividade e atividades",
            "category": "productivity",
            "instructions": "Detecte a atividade atual, calcule score de produtividade e sugira melhorias.",
            "tools": ["context", "scheduler"],
            "examples": ["O que estou fazendo?", "Como está minha produtividade?"],
            "tags": ["produtividade", "atividade", "foco"],
        },
        {
            "name": "Entertainment",
            "description": "Piadas, curiosidades e jogos",
            "category": "entertainment",
            "instructions": "Forneça entretenimento de qualidade: piadas limpas, curiosidades interessantes, jogos simples.",
            "tools": ["entertainment"],
            "examples": ["Dá uma piada", "Conta uma curiosidade", "Vamos jogar?"],
            "tags": ["entretenimento", "piadas", "jogos"],
        },
        {
            "name": "Smart Home Control",
            "description": "Controle dispositivos inteligentes",
            "category": "iot",
            "instructions": "Envie comandos para dispositivos IoT conectados. Gerencie luzes, sensores e automações.",
            "tools": ["desktop"],
            "examples": ["Acender luz", "Desligar TV", "Aumentar volume"],
            "tags": ["casa", "luz", "tv", "iot"],
        },
        {
            "name": "File Manager",
            "description": "Gerencia arquivos e pastas",
            "category": "files",
            "instructions": "Organize, busque e gerencie arquivos. Faça backup, mova, copie e renomeie arquivos.",
            "tools": ["turbo", "desktop"],
            "examples": ["Organizar downloads", "Fazer backup", "Buscar arquivos"],
            "tags": ["arquivos", "backup", "organizar"],
        },
        {
            "name": "Daily Briefing",
            "description": "Gera briefing diário completo",
            "category": "productivity",
            "instructions": "Compile clima, tarefas, calendário e notícias em um briefing matinal.",
            "tools": ["weather", "scheduler", "sys", "websearch"],
            "examples": ["Bom dia", "Me dê o briefing", "Resumo do dia"],
            "tags": ["manhã", "briefing", "resumo"],
        },
    ]

    def __init__(self, data_dir: Optional[Path] = None):
        self._data_dir = data_dir
        self._skills: dict[str, Skill] = {}
        self._counter = 0
        self._load()

        # Registrar skills padrão
        for skill_def in self.BUILTIN_SKILLS:
            self.register_skill(**skill_def)

    def _load(self) -> None:
        """Carrega skills customizadas do disco."""
        skills_file = self._data_dir / "skills.json" if self._data_dir else None
        if skills_file and skills_file.exists():
            try:
                data = json.loads(skills_file.read_text(encoding="utf-8"))
                for s in data.get("skills", []):
                    skill = Skill(**s)
                    self._skills[skill.id] = skill
                self._counter = data.get("counter", 0)
            except Exception:
                pass

    def _save(self) -> None:
        """Salva skills no disco."""
        skills_file = self._data_dir / "skills.json" if self._data_dir else None
        if skills_file:
            try:
                data = {
                    "skills": [asdict(s) for s in self._skills.values()],
                    "counter": self._counter,
                }
                skills_file.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception:
                pass

    def _next_id(self) -> str:
        self._counter += 1
        return f"skill_{self._counter}"

    def register_skill(
        self,
        name: str,
        description: str,
        category: str,
        instructions: str = "",
        tools: Optional[list[str]] = None,
        examples: Optional[list[str]] = None,
        tags: Optional[list[str]] = None,
        author: str = "A.R.I.S.",
        version: str = "1.0.0",
    ) -> Skill:
        """Registra uma nova skill."""
        # Verificar se já existe
        for skill in self._skills.values():
            if skill.name == name:
                return skill

        skill = Skill(
            id=self._next_id(),
            name=name,
            description=description,
            category=category,
            instructions=instructions,
            tools=tools or [],
            examples=examples or [],
            tags=tags or [],
            author=author,
            version=version,
        )
        self._skills[skill.id] = skill
        self._save()
        return skill

    def get_skill(self, name: str) -> Optional[Skill]:
        """Busca skill pelo nome."""
        for skill in self._skills.values():
            if skill.name.lower() == name.lower():
                return skill
        return None

    def search_skills(self, query: str) -> list[Skill]:
        """Busca skills por query."""
        query_lower = query.lower()
        results = []
        for skill in self._skills.values():
            if (query_lower in skill.name.lower() or
                query_lower in skill.description.lower() or
                any(query_lower in tag for tag in skill.tags)):
                results.append(skill)
        return results

    def get_skills_by_category(self, category: str) -> list[Skill]:
        """Retorna skills de uma categoria."""
        return [s for s in self._skills.values() if s.category == category]

    def enable_skill(self, name: str) -> str:
        """Ativa uma skill."""
        skill = self.get_skill(name)
        if skill:
            skill.enabled = True
            self._save()
            return f"Skill '{name}' ativada"
        return f"Skill '{name}' não encontrada"

    def disable_skill(self, name: str) -> str:
        """Desativa uma skill."""
        skill = self.get_skill(name)
        if skill:
            skill.enabled = False
            self._save()
            return f"Skill '{name}' desativada"
        return f"Skill '{name}' não encontrada"

    def get_skill_prompt(self, query: str) -> Optional[str]:
        """Retorna o prompt de uma skill baseado na query."""
        skills = self.search_skills(query)
        if not skills:
            return None

        skill = skills[0]
        if not skill.enabled:
            return None

        return (
            f"Skill ativa: {skill.name}\n"
            f"Instruções: {skill.instructions}\n"
            f"Ferramentas: {', '.join(skill.tools)}"
        )

    def list_categories(self) -> list[str]:
        """Lista todas as categorias."""
        return list(set(s.category for s in self._skills.values()))

    def get_stats(self) -> dict:
        """Retorna estatísticas."""
        return {
            "total": len(self._skills),
            "enabled": len([s for s in self._skills.values() if s.enabled]),
            "categories": len(self.list_categories()),
        }

    def format_skills(self) -> str:
        """Formata lista de skills."""
        lines = [f"🧩 Skills System — {self.get_stats()['total']} skills"]
        for category in sorted(self.list_categories()):
            skills = self.get_skills_by_category(category)
            lines.append(f"\n  📂 {category.upper()}")
            for skill in skills:
                status = "✅" if skill.enabled else "❌"
                lines.append(f"    {status} {skill.name} — {skill.description}")
        return "\n".join(lines)
