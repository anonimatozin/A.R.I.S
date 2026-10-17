"""World Model, User Model e Goals do A.R.I.S.

Módulo coeso que cobre:
- **Belief**: crenças com proveniência, confiança e histórico de revisão
- **User Model**: perfil do usuário (beliefs com category=user_profile)
- **Goals**: objetivos com status, prazo e importância
- **Prospective Reminders**: lembretes futuros com recorrência opcional
- **Follow-up**: detecção de prazos expirados e consultas ao usuário
- **Calendar Integration**: consulta Google Calendar para conflitos e rotina

Schema SQLite: 3 tabelas novas no banco unificado (beliefs, goals,
prospective_reminders), criadas automaticamente.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from core.memory_db import MemoryDB

# Import opcional do Calendar Manager
try:
    from core.calendar.service import CalendarManager, CalendarEvent
except ImportError:
    CalendarManager = None
    CalendarEvent = None

# ── Eventos ──────────────────────────────────────────────────

EVENT_BELIEF_CREATED = "belief.created"
EVENT_BELIEF_UPDATED = "belief.updated"
EVENT_GOAL_CREATED = "goal.created"
EVENT_GOAL_COMPLETED = "goal.completed"
EVENT_GOAL_ABANDONED = "goal.abandoned"
EVENT_REMINDER_CREATED = "reminder.created"
EVENT_REMINDER_TRIGGERED = "reminder.triggered"
EVENT_FOLLOWUP_SUGGESTION = "followup.suggestion"

WORLD_MODEL_EVENT_TYPES = frozenset({
    EVENT_BELIEF_CREATED,
    EVENT_BELIEF_UPDATED,
    EVENT_GOAL_CREATED,
    EVENT_GOAL_COMPLETED,
    EVENT_GOAL_ABANDONED,
    EVENT_REMINDER_CREATED,
    EVENT_REMINDER_TRIGGERED,
    EVENT_FOLLOWUP_SUGGESTION,
})

# ── Enums ────────────────────────────────────────────────────


class BeliefSource(Enum):
    """Origem da crença (proveniência)."""
    OBSERVED = "observed"          # Observação direta (visão, percepção)
    INFERRED = "inferred"          # Derivada de outras informações
    MEMORY = "memory"              # Recuperada de memória persistente
    USER_PROVIDED = "user_provided"  # Fornecida pelo usuário (alta confiança)
    HYPOTHESIS = "hypothesis"      # Hipótese (baixa confiança)
    UNKNOWN = "unknown"            # Desconhecido


class GoalStatus(Enum):
    """Status de um objetivo."""
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    BLOCKED = "blocked"


# ── Dataclasses ──────────────────────────────────────────────


@dataclass
class Belief:
    """Uma crença com proveniência e histórico de revisão.

    Quando o valor muda, a crença antiga recebe ``valid_until`` e
    uma nova entrada é criada com ``revision`` incrementado.
    """
    id: str
    category: str          # ex: 'general', 'user_profile', 'system'
    key: str               # ex: 'operador.cafe', 'pc.ram_gb'
    value: str             # valor textual
    source: BeliefSource
    confidence: float      # 0.0 a 1.0
    observed_at: str       # ISO datetime — quando observado
    valid_from: str        # ISO datetime — quando tornou-se válido
    valid_until: str | None  # None = ainda válido
    revision: int
    created_at: str

    def is_current(self) -> bool:
        return self.valid_until is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "key": self.key,
            "value": self.value,
            "source": self.source.value,
            "confidence": self.confidence,
            "observed_at": self.observed_at,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "revision": self.revision,
            "created_at": self.created_at,
        }


@dataclass
class Goal:
    """Um objetivo com status, prazo e importância."""
    id: str
    description: str
    status: GoalStatus
    importance: int            # 1-10
    deadline: str | None       # ISO datetime ou None
    created_at: str
    updated_at: str
    completed_at: str | None

    def is_overdue(self) -> bool:
        if self.deadline is None or self.status != GoalStatus.ACTIVE:
            return False
        try:
            dl = datetime.fromisoformat(self.deadline)
            return datetime.now() > dl
        except (ValueError, TypeError):
            return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "status": self.status.value,
            "importance": self.importance,
            "deadline": self.deadline,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }


@dataclass
class ProspectiveReminder:
    """Lembrete futuro, com recorrência opcional."""
    id: str
    text: str
    remind_at: str         # ISO datetime
    recurrence: str | None  # None, 'daily', 'weekly', 'monthly', 'yearly'
    last_triggered: str | None
    created_at: str
    is_active: bool

    def should_trigger(self, now: datetime | None = None) -> bool:
        """Verifica se o lembrete deve disparar agora."""
        if not self.is_active:
            return False
        now = now or datetime.now()
        try:
            remind_time = datetime.fromisoformat(self.remind_at)
            return now >= remind_time
        except (ValueError, TypeError):
            return False

    def advance_recurrence(self, now: datetime | None = None) -> str | None:
        """Avança para a próxima ocorrência. Retorna None se one-time."""
        if not self.recurrence:
            return None
        now = now or datetime.now()
        try:
            current = datetime.fromisoformat(self.remind_at)
        except (ValueError, TypeError):
            return None
        if self.recurrence == "daily":
            next_dt = current + timedelta(days=1)
        elif self.recurrence == "weekly":
            next_dt = current + timedelta(weeks=1)
        elif self.recurrence == "monthly":
            month = current.month + 1
            year = current.year
            if month > 12:
                month = 1
                year += 1
            day = min(current.day, 28)
            next_dt = current.replace(year=year, month=month, day=day)
        elif self.recurrence == "yearly":
            next_dt = current.replace(year=current.year + 1)
        else:
            return None
        return next_dt.isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "remind_at": self.remind_at,
            "recurrence": self.recurrence,
            "last_triggered": self.last_triggered,
            "created_at": self.created_at,
            "is_active": self.is_active,
        }


# ── Heurística de confiança ──────────────────────────────────

# Verbos/expressões que indicam compromisso real
_COMMITMENT_MARKERS = re.compile(
    r"(?i)\b("
    r"quero\s+(terminar|concluir|fazer|completar|resolver|implementar|criar)"
    r"|preciso\s+(terminar|concluir|fazer|completar|resolver|implementar|criar)"
    r"|vou\s+(terminar|concluir|fazer|completar|resolver|implementar|criar)"
    r"|prometo"
    r"|comprometo"
    r"|decidido\s+a"
    r"|meta\s+e"
    r"|objetivo\s+e"
    r")\b"
)

_DEADLINE_PATTERN = re.compile(
    r"(?i)(em\s+\d+\s+(dia|semana|m[eê]s|ano)s?"
    r"|at[eé]\s+(janeiro|fevereiro|mar[cç]o|abril|maio|junho"
    r"|julho|agosto|setembro|outubro|novembro|dezembro"
    r"|\d{4})"
    r"|prazo\s+de"
    r"|(pr[oó]ximo|pr[oó]xima)\s+(m[eê]s|ano|segunda|ter[cç]a|quarta|quinta|sexta|s[aá]bado|domingo)"
    r"|\d{1,2}\s+de\s+\w+\s+(de\s+)?\d{4})"
)

# Expressões que indicam pedido explícito de lembrete
_REMINDER_REQUEST = re.compile(
    r"(?i)\b("
    r"me\s+lembre"
    r"|lembra(?:r)?\s+(mim|disso|de\s+isso)"
    r"|agenda(?:r)?\s+(isso|um\s+lembrete)"
    r"|quero\s+que\s+lembre"
    r"|avise\s+(mim|quando)"
    r")\b"
)

# Padrões de recorrência que implícitamente pedem um lembrete
_RECURRENCE_PATTERN = re.compile(
    r"(?i)\b("
    r"todo\s+(dia|semana|m[eê]s|ano)"
    r"|a\s+cada\s+(dia|semana|m[eê]s|ano)"
    r"|anualmente"
    r"|mensalmente"
    r"|semanalmente"
    r"|diariamente"
    r")\b"
)

# Padrão "dia DD de Mês" — recorrência anual implícita
_IMPLICIT_YEARLY = re.compile(
    r"(?i)\bdia\s+\d{1,2}\s+de\s+"
    r"(janeiro|fevereiro|março|abril|maio|junho"
    r"|julho|agosto|setembro|outubro|novembro|dezembro)\b"
)

# Mapeia termos de recorrência para valores padrão
_RECURRENCE_MAP = {
    "dia": "daily",
    "semana": "weekly",
    "m[eê]s": "monthly",
    "mes": "monthly",
    "ano": "yearly",
    "anualmente": "yearly",
    "mensalmente": "monthly",
    "semanalmente": "weekly",
    "diariamente": "daily",
}


def classify_commitment(text: str) -> tuple[bool, bool, bool]:
    """Classifica se um texto é um compromisso explícito, pedido de lembrete
    ou contém padrão de recorrência.

    Returns:
        (is_commitment, is_reminder_request, has_recurrence)
    """
    is_reminder_request = bool(_REMINDER_REQUEST.search(text))
    is_commitment = bool(_COMMITMENT_MARKERS.search(text))
    has_recurrence = bool(_RECURRENCE_PATTERN.search(text))
    # "dia DD de Mês" sem "todo ano" também implica recorrência anual
    if not has_recurrence and _IMPLICIT_YEARLY.search(text):
        has_recurrence = True
    return is_commitment, is_reminder_request, has_recurrence


def extract_recurrence(text: str) -> str | None:
    """Extrai o tipo de recorrência de um texto (se houver)."""
    # Primeiro verifica padrão explícito "todo X"
    match = _RECURRENCE_PATTERN.search(text)
    if match:
        matched = match.group(0).lower()
        for pattern, value in _RECURRENCE_MAP.items():
            if re.search(pattern, matched):
                return value
    # Padrão implícito "dia DD de Mês" → yearly
    if _IMPLICIT_YEARLY.search(text):
        return "yearly"
    return None


def estimate_goal_confidence(text: str) -> float:
    """Estima a confiança de que uma frase é uma meta genuína.

    Retorna 0.0 a 1.0. Acima de 0.6 pode ser registrado como Goal.
    """
    score = 0.0

    is_commitment, is_reminder, is_recurrence = classify_commitment(text)
    if is_commitment:
        score += 0.4
    if is_reminder or is_recurrence:
        score += 0.5
    if _DEADLINE_PATTERN.search(text):
        score += 0.2

    # Repetição de intenção (pode ser verificada externamente)
    if text.lower().count("quero") >= 2 or text.lower().count("vou") >= 2:
        score += 0.1

    return min(score, 1.0)


# ── World Model ──────────────────────────────────────────────


class WorldModel:
    """World Model unificado: Beliefs, User Model, Goals, Reminders.

    Usa o MemoryDB existente para persistir novas tabelas.
    Integração opcional com Google Calendar para detecção de conflitos
    e enriquecimento de rotina.
    """

    def __init__(
        self,
        db: MemoryDB,
        logger: Any = None,
        calendar_manager: Any = None,
    ) -> None:
        self._db = db
        self._logger = logger
        self._calendar_manager = calendar_manager
        self._create_tables()

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        """Emite evento via callback se registrado."""
        if self._event_cb:
            self._event_cb(event_type, payload)

    def set_event_bus(self, cb: Any) -> None:
        """Registra callback para emissão de eventos.

        cb(event_type: str, payload: dict)
        """
        self._event_cb = cb

    # ── Schema ────────────────────────────────────────────────

    def _create_tables(self) -> None:
        self._db._execute("""
            CREATE TABLE IF NOT EXISTS beliefs (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                source TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 1.0,
                observed_at TEXT NOT NULL,
                valid_from TEXT NOT NULL,
                valid_until TEXT,
                revision INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)
        self._db._execute("""
            CREATE TABLE IF NOT EXISTS goals (
                id TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                importance INTEGER NOT NULL DEFAULT 5,
                deadline TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT
            )
        """)
        self._db._execute("""
            CREATE TABLE IF NOT EXISTS prospective_reminders (
                id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                remind_at TEXT NOT NULL,
                recurrence TEXT,
                last_triggered TEXT,
                created_at TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            )
        """)
        self._db._execute(
            "CREATE INDEX IF NOT EXISTS idx_beliefs_category ON beliefs(category)"
        )
        self._db._execute(
            "CREATE INDEX IF NOT EXISTS idx_beliefs_key ON beliefs(key)"
        )
        self._db._execute(
            "CREATE INDEX IF NOT EXISTS idx_goals_status ON goals(status)"
        )
        self._db._execute(
            "CREATE INDEX IF NOT EXISTS idx_reminders_active ON prospective_reminders(is_active)"
        )

    # ── Beliefs CRUD ──────────────────────────────────────────

    def create_belief(
        self,
        category: str,
        key: str,
        value: str,
        source: BeliefSource = BeliefSource.USER_PROVIDED,
        confidence: float = 1.0,
    ) -> Belief:
        """Cria uma nova crença. Se já existe uma ativa com a mesma
        category+key, arquiva a antiga (valid_until) e cria nova revisão.
        """
        now = datetime.now().isoformat()

        # Verifica se já existe crença ativa com mesma category+key
        existing = self._get_current_belief(category, key)
        revision = 1
        if existing:
            revision = existing.revision + 1
            self._archive_belief(existing.id, now)

        belief = Belief(
            id=uuid.uuid4().hex[:12],
            category=category,
            key=key,
            value=value,
            source=source,
            confidence=confidence,
            observed_at=now,
            valid_from=now,
            valid_until=None,
            revision=revision,
            created_at=now,
        )
        self._db._execute(
            """INSERT INTO beliefs
               (id, category, key, value, source, confidence,
                observed_at, valid_from, valid_until, revision, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                belief.id,
                belief.category,
                belief.key,
                belief.value,
                belief.source.value,
                belief.confidence,
                belief.observed_at,
                belief.valid_from,
                belief.valid_until,
                belief.revision,
                belief.created_at,
            ),
        )
        return belief

    def update_belief(
        self,
        category: str,
        key: str,
        new_value: str,
        source: BeliefSource = BeliefSource.USER_PROVIDED,
        confidence: float = 1.0,
    ) -> Belief:
        """Atualiza uma crença existente (cria nova revisão).

        Se não existe crença ativa, cria uma nova.
        """
        existing = self._get_current_belief(category, key)
        if existing and existing.value == new_value:
            return existing  # Sem mudança
        return self.create_belief(category, key, new_value, source, confidence)

    def get_belief(self, category: str, key: str) -> Belief | None:
        """Retorna a crença ativa mais recente para category+key."""
        return self._get_current_belief(category, key)

    def get_belief_history(self, category: str, key: str) -> list[Belief]:
        """Retorna todas as revisões de uma crença (mais recente primeiro)."""
        rows = self._db._execute(
            """SELECT * FROM beliefs WHERE category = ? AND key = ?
               ORDER BY revision DESC""",
            (category, key),
            fetch=True,
        )
        return [self._row_to_belief(r) for r in rows]

    def search_beliefs(
        self,
        category: str | None = None,
        query: str = "",
        only_current: bool = True,
        limit: int = 50,
    ) -> list[Belief]:
        """Busca crenças por categoria e/ou texto."""
        conditions: list[str] = []
        params: list[Any] = []
        if only_current:
            conditions.append("valid_until IS NULL")
        if category:
            conditions.append("category = ?")
            params.append(category)
        if query:
            conditions.append("(key LIKE ? OR value LIKE ?)")
            q = f"%{query}%"
            params.extend([q, q])
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT * FROM beliefs {where} ORDER BY revision DESC LIMIT ?"
        params.append(limit)
        rows = self._db._execute(sql, tuple(params), fetch=True)
        return [self._row_to_belief(r) for r in rows]

    def _get_current_belief(self, category: str, key: str) -> Belief | None:
        rows = self._db._execute(
            """SELECT * FROM beliefs
               WHERE category = ? AND key = ? AND valid_until IS NULL
               ORDER BY revision DESC LIMIT 1""",
            (category, key),
            fetch=True,
        )
        return self._row_to_belief(rows[0]) if rows else None

    def _archive_belief(self, belief_id: str, valid_until: str) -> None:
        self._db._execute(
            "UPDATE beliefs SET valid_until = ? WHERE id = ?",
            (valid_until, belief_id),
        )

    def _row_to_belief(self, row: dict[str, Any]) -> Belief:
        return Belief(
            id=row["id"],
            category=row["category"],
            key=row["key"],
            value=row["value"],
            source=BeliefSource(row["source"]),
            confidence=row["confidence"],
            observed_at=row["observed_at"],
            valid_from=row["valid_from"],
            valid_until=row["valid_until"],
            revision=row["revision"],
            created_at=row["created_at"],
        )

    # ── User Model (Beliefs com category=user_profile) ────────

    def set_user_preference(
        self,
        key: str,
        value: str,
        confidence: float = 1.0,
    ) -> Belief:
        """Registra uma preferência do usuário."""
        return self.create_belief(
            category="user_profile",
            key=key,
            value=value,
            source=BeliefSource.USER_PROVIDED,
            confidence=confidence,
        )

    def get_user_preference(self, key: str) -> str | None:
        """Retorna o valor de uma preferência do usuário."""
        belief = self.get_belief("user_profile", key)
        return belief.value if belief else None

    def get_user_profile(self) -> dict[str, str]:
        """Retorna todas as preferências ativas do usuário."""
        beliefs = self.search_beliefs(category="user_profile", only_current=True)
        return {b.key: b.value for b in beliefs}

    # ── Goals CRUD ────────────────────────────────────────────

    def create_goal(
        self,
        description: str,
        importance: int = 5,
        deadline: str | None = None,
    ) -> Goal:
        """Cria um novo objetivo ativo."""
        now = datetime.now().isoformat()
        goal = Goal(
            id=uuid.uuid4().hex[:12],
            description=description,
            status=GoalStatus.ACTIVE,
            importance=max(1, min(10, importance)),
            deadline=deadline,
            created_at=now,
            updated_at=now,
            completed_at=None,
        )
        self._db._execute(
            """INSERT INTO goals
               (id, description, status, importance, deadline,
                created_at, updated_at, completed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                goal.id,
                goal.description,
                goal.status.value,
                goal.importance,
                goal.deadline,
                goal.created_at,
                goal.updated_at,
                goal.completed_at,
            ),
        )
        return goal

    def complete_goal(self, goal_id: str) -> Goal | None:
        """Marca um objetivo como concluído."""
        return self._update_goal_status(goal_id, GoalStatus.COMPLETED)

    def abandon_goal(self, goal_id: str) -> Goal | None:
        """Marca um objetivo como abandonado."""
        return self._update_goal_status(goal_id, GoalStatus.ABANDONED)

    def block_goal(self, goal_id: str) -> Goal | None:
        """Marca um objetivo como bloqueado."""
        return self._update_goal_status(goal_id, GoalStatus.BLOCKED)

    def get_goal(self, goal_id: str) -> Goal | None:
        rows = self._db._execute(
            "SELECT * FROM goals WHERE id = ?", (goal_id,), fetch=True
        )
        return self._row_to_goal(rows[0]) if rows else None

    def get_active_goals(self) -> list[Goal]:
        rows = self._db._execute(
            "SELECT * FROM goals WHERE status = 'active' ORDER BY importance DESC",
            fetch=True,
        )
        return [self._row_to_goal(r) for r in rows]

    def get_overdue_goals(self) -> list[Goal]:
        """Retorna objetivos ativos cujo prazo já passou."""
        now = datetime.now().isoformat()
        rows = self._db._execute(
            """SELECT * FROM goals
               WHERE status = 'active' AND deadline IS NOT NULL AND deadline < ?
               ORDER BY deadline ASC""",
            (now,),
            fetch=True,
        )
        return [self._row_to_goal(r) for r in rows]

    def _update_goal_status(self, goal_id: str, status: GoalStatus) -> Goal | None:
        goal = self.get_goal(goal_id)
        if not goal:
            return None
        now = datetime.now().isoformat()
        completed_at = now if status == GoalStatus.COMPLETED else None
        self._db._execute(
            """UPDATE goals
               SET status = ?, updated_at = ?, completed_at = ?
               WHERE id = ?""",
            (status.value, now, completed_at, goal_id),
        )
        return self.get_goal(goal_id)

    def _row_to_goal(self, row: dict[str, Any]) -> Goal:
        return Goal(
            id=row["id"],
            description=row["description"],
            status=GoalStatus(row["status"]),
            importance=row["importance"],
            deadline=row["deadline"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
        )

    # ── Prospective Reminders CRUD ────────────────────────────

    def create_reminder(
        self,
        text: str,
        remind_at: str,
        recurrence: str | None = None,
    ) -> ProspectiveReminder:
        """Cria um lembrete futuro."""
        now = datetime.now().isoformat()
        reminder = ProspectiveReminder(
            id=uuid.uuid4().hex[:12],
            text=text,
            remind_at=remind_at,
            recurrence=recurrence,
            last_triggered=None,
            created_at=now,
            is_active=True,
        )
        self._db._execute(
            """INSERT INTO prospective_reminders
               (id, text, remind_at, recurrence, last_triggered,
                created_at, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                reminder.id,
                reminder.text,
                reminder.remind_at,
                reminder.recurrence,
                reminder.last_triggered,
                reminder.created_at,
                1 if reminder.is_active else 0,
            ),
        )
        return reminder

    def get_due_reminders(self) -> list[ProspectiveReminder]:
        """Retorna lembretes que devem disparar agora."""
        now = datetime.now()
        rows = self._db._execute(
            "SELECT * FROM prospective_reminders WHERE is_active = 1",
            fetch=True,
        )
        due = []
        for r in rows:
            rem = self._row_to_reminder(r)
            if rem.should_trigger(now):
                due.append(rem)
        return due

    def trigger_reminder(self, reminder_id: str) -> ProspectiveReminder | None:
        """Dispara um lembrete: registra last_triggered e avança recorrência."""
        rows = self._db._execute(
            "SELECT * FROM prospective_reminders WHERE id = ?",
            (reminder_id,),
            fetch=True,
        )
        if not rows:
            return None
        rem = self._row_to_reminder(rows[0])
        now = datetime.now().isoformat()
        next_remind = rem.advance_recurrence()
        if next_remind:
            self._db._execute(
                """UPDATE prospective_reminders
                   SET last_triggered = ?, remind_at = ?
                   WHERE id = ?""",
                (now, next_remind, reminder_id),
            )
        else:
            self._db._execute(
                """UPDATE prospective_reminders
                   SET last_triggered = ?, is_active = 0
                   WHERE id = ?""",
                (now, reminder_id),
            )
        return self._get_reminder(reminder_id)

    def _get_reminder(self, reminder_id: str) -> ProspectiveReminder | None:
        rows = self._db._execute(
            "SELECT * FROM prospective_reminders WHERE id = ?",
            (reminder_id,),
            fetch=True,
        )
        return self._row_to_reminder(rows[0]) if rows else None

    def _row_to_reminder(self, row: dict[str, Any]) -> ProspectiveReminder:
        return ProspectiveReminder(
            id=row["id"],
            text=row["text"],
            remind_at=row["remind_at"],
            recurrence=row["recurrence"],
            last_triggered=row["last_triggered"],
            created_at=row["created_at"],
            is_active=bool(row["is_active"]),
        )

    # ── Follow-up ─────────────────────────────────────────────

    def check_follow_ups(self) -> list[str]:
        """Verifica prazos expirados e gera sugestões de follow-up.

        Retorna lista de strings prontas para consulta ao usuário.
        Nenhuma ação é tomada automaticamente.
        """
        suggestions: list[str] = []
        overdue = self.get_overdue_goals()
        for goal in overdue:
            try:
                dl = datetime.fromisoformat(goal.deadline)
                days = (datetime.now() - dl).days
                if days == 1:
                    suggestions.append(
                        f"O objetivo '{goal.description}' passou do prazo ontem. "
                        f"Deseja atualizá-lo ou abandoná-lo?"
                    )
                else:
                    suggestions.append(
                        f"O objetivo '{goal.description}' está {days} dias "
                        f"atrasado (prazo: {goal.deadline[:10]}). "
                        f"Deseja atualizá-lo ou abandoná-lo?"
                    )
            except (ValueError, TypeError):
                suggestions.append(
                    f"O objetivo '{goal.description}' está com prazo expirado. "
                    f"Deseja atualizá-lo ou abandoná-lo?"
                )

        due_reminders = self.get_due_reminders()
        for rem in due_reminders:
            suggestions.append(
                f"Lembrete pendente: '{rem.text}' "
                f"(agendado para {rem.remind_at[:16]})."
            )

        return suggestions

    # ── Integração: processar texto do usuário ────────────────

    def process_user_text(self, text: str) -> dict[str, Any] | None:
        """Analisa texto do usuário e cria Goal/Reminder quando apropriado.

        Returns:
            dict com tipo de ação e dados, ou None se nada foi criado.
        """
        confidence = estimate_goal_confidence(text)
        is_commitment, is_reminder, has_recurrence = classify_commitment(text)

        # Padrão de recorrência → tenta criar lembrete recorrente
        if has_recurrence:
            recurrence = extract_recurrence(text)
            remind_at = self._extract_recurrence_time(text, recurrence)
            if remind_at is None:
                # Informação insuficiente — pergunta ao usuário
                missing = self._what_is_missing(text, recurrence)
                return {
                    "action": "needs_clarification",
                    "confidence": confidence,
                    "suggestion": missing,
                }
            reminder = self.create_reminder(
                text=text, remind_at=remind_at, recurrence=recurrence,
            )
            return {"action": "reminder_created", "reminder": reminder, "confidence": confidence}

        # Pedido explícito de lembrete → tenta resolver automaticamente
        if is_reminder:
            resolved = self._resolve_reminder_time(text)
            if resolved is not None:
                remind_at, confidence_boost, source = resolved
                reminder = self.create_reminder(text=text, remind_at=remind_at)
                return {
                    "action": "reminder_created",
                    "reminder": reminder,
                    "confidence": min(confidence + confidence_boost, 1.0),
                    "source": source,
                }
            # Sem informação suficiente → pergunta ao usuário
            return {
                "action": "reminder_request",
                "confidence": confidence,
                "suggestion": (
                    "Você pediu um lembrete. Para agendá-lo, me diga "
                    "quando quer ser lembrado (ex: 'daqui a duas semanas', "
                    "'todo dia às 9h')."
                ),
            }

        # Compromisso com confiança alta → cria Goal
        if is_commitment and confidence >= 0.6:
            goal = self.create_goal(description=text, importance=6)
            return {"action": "goal_created", "goal": goal, "confidence": confidence}

        # Compromisso com confiança média → pergunta ao usuário
        if is_commitment and confidence >= 0.3:
            return {
                "action": "ambiguous",
                "confidence": confidence,
                "suggestion": (
                    f"Isso que você disse parece uma meta: '{text}'. "
                    f"Quer que eu registre isso como um objetivo, "
                    f"ou foi só um comentário?"
                ),
            }

        return None

    def _extract_recurrence_time(self, text: str, recurrence: str | None) -> str | None:
        """Tenta extrair um horário/índice de um texto para recorrência.

        Returns:
            ISO datetime se informação suficiente, None se faltar informação
            essencial (ex: "todo ano, dia 12" sem mês → None).

        Ex: "todo dia às 9h" → hoje às 09:00
        Ex: "meu aniversário é dia 12 de outubro" → 2026-10-12T09:00:00
        Ex: "todo ano, dia 12" → None (mês desconhecido)
        """
        import re as _re

        now = datetime.now()

        # Padrão "dia DD de Mês" (ex: "dia 12 de outubro")
        month_map = {
            "janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4,
            "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
            "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
        }
        full_date_match = _re.search(
            r"(?i)dia\s+(\d{1,2})\s+de\s+([a-zà-ú]+)",
            text,
        )
        if full_date_match:
            day = int(full_date_match.group(1))
            month_name = full_date_match.group(2).lower()
            month = month_map.get(month_name)
            if month and 1 <= day <= 31:
                year = now.year
                try:
                    target = datetime(year, month, day, 9, 0, 0)
                except ValueError:
                    target = datetime(year, month, 28, 9, 0, 0)
                if target <= now:
                    year += 1
                    try:
                        target = datetime(year, month, day, 9, 0, 0)
                    except ValueError:
                        target = datetime(year, month, 28, 9, 0, 0)
                return target.isoformat()

        # Padrão "dia DD" sem mês (ex: "todo ano, dia 12")
        day_match = _re.search(r"(?i)dia\s+(\d{1,2})", text)
        if day_match:
            day = int(day_match.group(1))
            day = max(1, min(31, day))
            # Para recorrência anual, mês é obrigatório
            if recurrence == "yearly":
                return None
            # Para recorrência mensal/diária/semanal, usa mês atual
            month = now.month
            year = now.year
            try:
                target = datetime(year, month, day, 9, 0, 0)
            except ValueError:
                target = datetime(year, month, 28, 9, 0, 0)
            if target <= now:
                if month == 12:
                    month = 1
                    year += 1
                else:
                    month += 1
                try:
                    target = datetime(year, month, day, 9, 0, 0)
                except ValueError:
                    target = datetime(year, month, 28, 9, 0, 0)
            return target.isoformat()

        # Padrão "às HHh" ou "às HH:MM"
        time_match = _re.search(r"(?i)[àa]s\s+(\d{1,2})[h:](\d{0,2})", text)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2)) if time_match.group(2) else 0
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            return target.isoformat()

        # Fallback: "daqui a X semanas/dias"
        from_match = _re.search(
            r"(?i)daqui\s+a\s+(\d+)\s+(dia|semana|m[eê]s|ano)s?", text
        )
        if from_match:
            amount = int(from_match.group(1))
            unit = from_match.group(2).lower()
            if "dia" in unit:
                target = now + timedelta(days=amount)
            elif "semana" in unit:
                target = now + timedelta(weeks=amount)
            elif "m" in unit:
                target = now + timedelta(days=amount * 30)
            elif "ano" in unit:
                target = now + timedelta(days=amount * 365)
            else:
                target = now + timedelta(days=amount)
            return target.replace(hour=9, minute=0, second=0).isoformat()

        # Sem informação de data suficiente
        return None

    # ── Resolução de horário para reminders ───────────────────

    def _resolve_reminder_time(self, text: str) -> tuple[str, float, str] | None:
        """Tenta resolver um horário para lembrete usando User Model + Calendar.

        Returns:
            (remind_at_iso, confidence_boost, source) ou None se
            não há informação suficiente.

        Points de extensão (Google Calendar integration):
        - Consulta calendário real via API para detectar conflitos.
        - O parâmetro `source` indica a fonte: "user_model", "calendar",
          ou "default" para facilitar rastreabilidade.
        """
        import re as _re

        now = datetime.now()

        # 1. Extrai período relativo do texto
        base_date = self._parse_relative_time(text, now)
        if base_date is None:
            return None

        # 2. Consulta User Model + Calendar para rotina do usuário
        routine = self._parse_routine_beliefs()
        if not routine:
            # Sem dados de rotina → não inventa horário
            return None

        # 3. Encontra horário livre evitando períodos ocupados
        suggested_time = self._find_free_slot(base_date, routine)
        if suggested_time is None:
            return None

        # 4. Google Calendar: verifica conflitos reais
        if self._calendar_manager and CalendarManager:
            try:
                end_time = suggested_time + timedelta(hours=1)  # assume 1h duração
                conflicts = self._calendar_manager.check_conflicts(
                    suggested_time, end_time
                )
                if conflicts:
                    # Tentar próximo slot livre
                    for _ in range(3):  # tentar até 3 alternativas
                        suggested_time += timedelta(hours=1)
                        end_time = suggested_time + timedelta(hours=1)
                        conflicts = self._calendar_manager.check_conflicts(
                            suggested_time, end_time
                        )
                        if not conflicts:
                            break
                    if conflicts:
                        # Ainda tem conflito - avisa mas retorna o horário
                        source_label = f"calendar_conflict ({len(conflicts)} conflitos)"
                        confidence_boost = 0.1
                        return (suggested_time.isoformat(), confidence_boost, source_label)
            except Exception as e:
                if self._logger:
                    self._logger.debug(f"Calendar conflict check failed: {e}")

        # 5. Calcula confiança baseada na qualidade dos dados
        source_count = routine.get("source_count", 0)
        confidence_boost = 0.3 if source_count >= 2 else 0.15
        source_label = f"user_model ({source_count} fontes)"

        return (suggested_time.isoformat(), confidence_boost, source_label)

    def _parse_relative_time(self, text: str, now: datetime) -> datetime | None:
        """Extrai um período relativo de um texto.

        Ex: "daqui a duas semanas" → now + 2 semanas
        Ex: "amanhã" → now + 1 dia
        Ex: "próxima segunda" → próxima segunda-feira
        """
        import re as _re

        # Mapeia palavras de número em português para dígitos
        word_to_num = {
            "um": 1, "uma": 1, "dois": 2, "duas": 2,
            "três": 3, "tres": 3, "quatro": 4, "cinco": 5,
            "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10,
        }

        # "daqui a X unidades" (dígitos ou palavras)
        match = _re.search(
            r"(?i)daqui\s+a\s+(\d+|"
            + "|".join(word_to_num.keys())
            + r")\s+(dia|semana|m[eê]s|ano)s?", text
        )
        if match:
            num_str = match.group(1).lower()
            amount = word_to_num.get(num_str) or int(num_str)
            unit = match.group(2).lower()
            if "dia" in unit:
                return now + timedelta(days=amount)
            elif "semana" in unit:
                return now + timedelta(weeks=amount)
            elif "m" in unit:
                return now + timedelta(days=amount * 30)
            elif "ano" in unit:
                return now + timedelta(days=amount * 365)

        # "amanhã"
        if _re.search(r"(?i)\bamanh[aã]\b", text):
            return now + timedelta(days=1)

        # "hoje"
        if _re.search(r"(?i)\bhoje\b", text):
            return now

        # "próxima/próximo + dia da semana"
        weekday_map = {
            "segunda": 0, "terca": 1, "terça": 1, "quarta": 2,
            "quinta": 3, "sexta": 4, "sabado": 5, "sábado": 5, "domingo": 6,
        }
        for name, weekday in weekday_map.items():
            if _re.search(rf"(?i)pr[óo]xim[oa]\s+{name}", text):
                days_ahead = (weekday - now.weekday()) % 7
                if days_ahead == 0:
                    days_ahead = 7
                return now + timedelta(days=days_ahead)

        return None

    def _parse_routine_beliefs(self) -> dict[str, Any] | None:
        """Extrai informações de rotina do User Model + Google Calendar.

        Returns:
            dict com:
            - busy_periods: list of (start_hour, end_hour) tuples
            - quiet_hours: list of (start_hour, end_hour) tuples
            - preferred_hours: list of preferred hours
            - calendar_events: list of CalendarEvent for today (if available)
            - source_count: número de crenças consultadas
            None se não há informação suficiente.

        Points de extensão (Google Calendar integration):
        - Mescla dados do calendário real com as crenças do User Model.
        - A estrutura de retorno (busy_periods, quiet_hours) é compatível
          com dados de calendário Google.
        """
        beliefs = self.search_beliefs(
            category="user_profile", query="horário", only_current=True,
        )
        routine_keywords = ["aula", "trabalho", "faculdade", "universidade",
                           "hora", "horário", "horario", "rotina", "manhã",
                           "noite", "tarde", "período", "periodo"]
        for kw in routine_keywords:
            found = self.search_beliefs(
                category="user_profile", query=kw, only_current=True,
            )
            for b in found:
                if b.id not in {fb.id for fb in beliefs}:
                    beliefs.append(b)

        busy_periods: list[tuple[int, int]] = []
        quiet_periods: list[tuple[int, int]] = []
        preferred_hours: list[int] = []
        calendar_events: list = []

        for belief in beliefs:
            text = belief.value.lower()
            period_match = re.search(
                r"(?:das?|de)\s+(\d{1,2})\s*[h:]"
                r"(?:\d{0,2})?\s*(?:às|a)\s+(\d{1,2})\s*[h:]?",
                text,
            )
            if period_match:
                start = int(period_match.group(1))
                end = int(period_match.group(2))
                if start < end:
                    busy_periods.append((start, end))
                continue

            quiet_match = re.search(
                r"(?i)(?:n[aã]o\s+)?(?:gosta|quer|deseja)\s+.*?"
                r"(?:antes|antes das)\s+(\d{1,2})\s*[h:]",
                text,
            )
            if quiet_match:
                hour = int(quiet_match.group(1))
                quiet_periods.append((0, hour))
                continue

            wake_match = re.search(
                r"(?i)(?:acorda|come[cç]a|inicia)\s+(?:às\s+)?(\d{1,2})\s*[h:]",
                text,
            )
            if wake_match:
                hour = int(wake_match.group(1))
                quiet_periods.append((0, hour))
                continue

            sleep_match = re.search(
                r"(?i)(?:dorme|termina|encerra)\s+(?:às\s+)?(\d{1,2})\s*[h:]",
                text,
            )
            if sleep_match:
                hour = int(sleep_match.group(1))
                quiet_periods.append((hour, 24))
                continue

        # ── Google Calendar Integration ──
        if self._calendar_manager and CalendarManager:
            try:
                today = datetime.now()
                day_start = today.replace(hour=0, minute=0, second=0, microsecond=0)
                day_end = today.replace(hour=23, minute=59, second=59, microsecond=0)
                cal_events = self._calendar_manager.list_events(
                    time_min=day_start,
                    time_max=day_end,
                    max_results=50,
                )
                if cal_events:
                    calendar_events = cal_events
                    for evt in cal_events:
                        # Converter eventos do calendário para busy_periods
                        start_hour = evt.start.hour
                        end_hour = evt.end.hour
                        if evt.end.minute > 0:
                            end_hour += 1
                        if start_hour < end_hour:
                            busy_periods.append((start_hour, end_hour))
            except Exception as e:
                if self._logger:
                    self._logger.debug(f"Calendar query failed in routine: {e}")

        if not busy_periods and not quiet_periods and not calendar_events:
            return None

        return {
            "busy_periods": busy_periods,
            "quiet_periods": quiet_periods,
            "preferred_hours": preferred_hours,
            "calendar_events": calendar_events,
            "source_count": len(beliefs) + len(calendar_events),
        }

    def _find_free_slot(
        self,
        base_date: datetime,
        routine: dict[str, Any],
    ) -> datetime | None:
        """Encontra um horário livre no dia baseado na rotina.

        Prioriza horários entre 9h e 18h, evitando períodos ocupados.
        Se o período base já passou ou cai em horário ocupado, avança.
        """
        busy = routine.get("busy_periods", [])
        quiet = routine.get("quiet_periods", [])

        # Horários candidatos (priorizando período comercial)
        candidates = [14, 15, 16, 10, 11, 9, 17, 8]

        for hour in candidates:
            # Verifica se está em período ocupado
            in_busy = any(s <= hour < e for s, e in busy)
            in_quiet = any(s <= hour < e for s, e in quiet)
            if not in_busy and not in_quiet:
                return base_date.replace(hour=hour, minute=0, second=0, microsecond=0)

        # Fallback: 14h (meio da tarde, geralmente seguro)
        return base_date.replace(hour=14, minute=0, second=0, microsecond=0)

    def _what_is_missing(self, text: str, recurrence: str | None) -> str:
        """Gera uma pergunta específica sobre informação faltante."""
        if recurrence == "yearly":
            has_day = bool(re.search(r"(?i)dia\s+\d{1,2}", text))
            has_month = bool(re.search(
                r"(?i)de\s+(janeiro|fevereiro|março|abril|maio|junho"
                r"|julho|agosto|setembro|outubro|novembro|dezembro)",
                text,
            ))
            if has_day and not has_month:
                day_match = re.search(r"(?i)dia\s+(\d{1,2})", text)
                day = day_match.group(1) if day_match else "?"
                return (
                    f"Entendi que é todo ano, mas em que mês é dia {day}? "
                    f"Por exemplo: 'dia {day} de outubro'."
                )
            return "Entendi que é algo recorrente, mas preciso saber a data completa. Em que dia e mês?"

        if recurrence == "monthly":
            return "Entendi que é todo mês, mas em que dia?"

        return "Preciso de mais detalhes para agendar. Pode especificar quando?"

    # ── Calendar Integration: Create Events from Goals/Reminders ──

    def create_calendar_event_from_goal(
        self,
        goal_id: str,
        duration_minutes: int = 60,
        account_id: str | None = None,
    ) -> tuple[CalendarEvent | None, list[CalendarEvent]]:
        """Cria evento no Google Calendar a partir de um Goal.

        Verifica conflitos antes de criar. Se houver conflito,
        retorna (None, lista_conflitos) para o usuário decidir.

        Returns:
            (evento_criado, conflitos) — conflitos vazio = sucesso
        """
        if not self._calendar_manager or not CalendarManager:
            return (None, [])

        goal = self.get_goal(goal_id)
        if not goal:
            return (None, [])

        # Tentar extrair data/hora do goal ou usar deadline
        start_time = None
        if goal.deadline:
            try:
                start_time = datetime.fromisoformat(goal.deadline)
            except (ValueError, TypeError):
                pass

        if not start_time:
            start_time = datetime.now().replace(hour=14, minute=0, second=0, microsecond=0)

        end_time = start_time + timedelta(minutes=duration_minutes)

        # Verificar conflitos
        conflicts = self._calendar_manager.check_conflicts(
            start_time, end_time, account_id=account_id
        )

        if conflicts:
            return (None, conflicts)

        # Criar evento
        event = self._calendar_manager.create_event(
            summary=goal.description,
            start=start_time,
            end=end_time,
            description=f"Goal A.R.I.S.: {goal.description}",
            account_id=account_id,
        )

        return (event, [])

    def create_calendar_event_from_reminder(
        self,
        reminder_id: str,
        duration_minutes: int = 30,
        account_id: str | None = None,
    ) -> tuple[CalendarEvent | None, list[CalendarEvent]]:
        """Cria evento no Google Calendar a partir de um ProspectiveReminder."""
        if not self._calendar_manager or not CalendarManager:
            return (None, [])

        rem = self._get_reminder(reminder_id)
        if not rem:
            return (None, [])

        try:
            start_time = datetime.fromisoformat(rem.remind_at)
        except (ValueError, TypeError):
            return (None, [])

        end_time = start_time + timedelta(minutes=duration_minutes)

        conflicts = self._calendar_manager.check_conflicts(
            start_time, end_time, account_id=account_id
        )

        if conflicts:
            return (None, conflicts)

        event = self._calendar_manager.create_event(
            summary=rem.text,
            start=start_time,
            end=end_time,
            description=f"Lembrete A.R.I.S.: {rem.text}",
            account_id=account_id,
        )

        return (event, [])

    def suggest_meeting_time(
        self,
        duration_minutes: int = 60,
        preferred_date: datetime | None = None,
        account_id: str | None = None,
    ) -> tuple[datetime | None, list[CalendarEvent]]:
        """Sugere horário livre para reunião, verificando Calendar real.

        Returns:
            (horário_sugerido, conflitos_se_houver)
        """
        if not self._calendar_manager or not CalendarManager:
            return (None, [])

        base = preferred_date or datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)

        # Buscar rotina + calendar
        routine = self._parse_routine_beliefs() or {}
        busy = routine.get("busy_periods", [])
        quiet = routine.get("quiet_periods", [])

        # Candidatos: 9h-18h
        candidates = [9, 10, 11, 14, 15, 16, 17]

        for hour in candidates:
            if any(s <= hour < e for s, e in busy):
                continue
            if any(s <= hour < e for s, e in quiet):
                continue

            start = base.replace(hour=hour, minute=0, second=0, microsecond=0)
            end = start + timedelta(minutes=duration_minutes)

            conflicts = self._calendar_manager.check_conflicts(
                start, end, account_id=account_id
            )
            if not conflicts:
                return (start, [])

        return (None, [])
