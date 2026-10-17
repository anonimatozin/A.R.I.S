"""Entretenimento do A.R.I.S.

Piadas, curiosidades, frases motivacionais, jogos simples.
"""

import json
import random
from pathlib import Path


class Entertainment:
    """Módulo de entretenimento."""

    def __init__(self, data_dir: Path | None = None):
        self._data_dir = data_dir
        self._jokes = self._load_jokes()
        self._curiosities = self._load_curiosities()
        self._quotes = self._load_quotes()

    def _load_jokes(self) -> list[str]:
        """Carrega piadas."""
        return [
            "Por que o programador usa óculos? Porque não consegue C#.",
            "Qual a linguagem de programação favorita do diabo? C# (C Sharp)... não, C-HELL.",
            "Um programador foi ao mercado. Comprou 10 ovos. Em casa, eram 8. Bug.",
            "Por que o JavaScript se vestiu de sobretudo? Porque estava fazendo frio (Cold).",
            "SQL e NoSQL se encontraram. SQL disse: 'Eu não te SELECT.' NoSQL respondeu: 'E eu não te INSERT.'",
            "Como o programador apaga a lâmpada? Ele desliga e liga de novo (reboot).",
            "Por que o programador foi ao bar? Para fazer um push.",
            "Qual a comida favorita do programador? Spaghetti code... e pizza.",
            "Um bug entrou num bar. O barman disse: 'Não servimos seu tipo aqui.' O bug respondeu: 'Mas eu já estou em todo lugar!'",
            "Por que o programador prefere escuro? Porque light attracts bugs.",
            "Um NULL entra num bar. O barman pergunta: 'O que quer?' NULL responde: 'Nada.'",
            "Por que o Python não é agressivo? Porque ele não tem dentes (teeth -> try/except).",
            "Qual a estação favorita do programador? O debug (de-bug).",
            "Por que o programador é péssimo no tênis? Porque ele sempre faz faults.",
        ]

    def _load_curiosities(self) -> list[str]:
        """Carrega curiosidades de TI."""
        return [
            "O primeiro bug literal era um inseto preso num relé do Harvard Mark II em 1947.",
            "Python foi criado por Guido van Rossum como um hobby durante o Natal de 1989.",
            "O nome 'JavaScript' não tem nada a ver com Java. Foi marketing puro.",
            "O email foi inventado antes da World Wide Web.",
            "O primeiro domínio registrado foi symbolics.com em 1985.",
            "O Google processa mais de 8.5 bilhões de pesquisas por dia.",
            "O termo 'bug' vem do typingsJapgolly moth (mariposa) que causou um curto-circuito no Harvard Mark II.",
            "O Windows 1.0 foi lançado em 1985 e custava $100.",
            "O世界上第一个计算机程序 foi escrito por Ada Lovelace em 1843.",
            "O GitHub tem mais de 200 milhões de repositórios.",
            "A primeira mensagem enviada via ARPANET ( precursor da internet) foi 'LO' — era para ser 'LOGIN' mas o sistema travou.",
            "Java foi originalmente chamado de 'Oak' (carvalho).",
            "O Linux foi criado como um hobby por Linus Torvalds em 1991.",
            "O MySQL foi inspirado em um banco de dados chamado mSQL.",
            "O primeiro emoji foi criado por Shigetaka Kurita no Japão em 1999.",
        ]

    def _load_quotes(self) -> list[str]:
        """Carrega frases motivacionais."""
        return [
            "A persistência é o caminho do êxito. — Charles Chaplin",
            "O sucesso é ir de fracasso em fracasso sem perder o entusiasmo. — Winston Churchill",
            "Não é sobre ter tempo, é sobre criar tempo. — Anônimo",
            "O futuro pertence àqueles que acreditam na beleza de seus sonhos. — Eleanor Roosevelt",
            "A melhor maneira de prever o futuro é criá-lo. — Peter Drucker",
            "O único modo de fazer um bom trabalho é amar o que você faz. — Steve Jobs",
            "Disciplina é escolher entre o que você quer agora e o que você mais quer. — Abraham Lincoln",
            "Não espere por oportunidades. Crie-as. — George Bernard Shaw",
            "O que podemos ouvir, podemos imaginar. O que podemos imaginar, podemos realizar. — Anônimo",
            "A tecnologia é melhor quando une as pessoas. — Matt Mullenweg",
            "Se você está indo pelo caminho certo e continua caminhando, eventualmente chegará ao seu destino. — Walt Disney",
            "A imaginação é mais importante que o conhecimento. — Albert Einstein",
        ]

    def get_random_joke(self) -> str:
        """Retorna uma piada aleatória."""
        return f"🎭 {random.choice(self._jokes)}"

    def get_random_curiosity(self) -> str:
        """Retorna uma curiosidade aleatória."""
        return f"🧠 {random.choice(self._curiosities)}"

    def get_random_quote(self) -> str:
        """Retorna uma frase motivacional."""
        return f"💡 {random.choice(self._quotes)}"

    def guess_number_game(self) -> str:
        """Inicia o jogo de adivinhar número."""
        number = random.randint(1, 100)
        # Salvar estado do jogo
        if self._data_dir:
            game_file = self._data_dir / "guess_game.json"
            game_file.write_text(json.dumps({"number": number, "attempts": 0}), encoding="utf-8")
        return "🎯 Pensei em um número de 1 a 100. Tente adivinhar! (Digite o número)"

    def check_guess(self, guess: int) -> str:
        """Verifica um palpite."""
        if not self._data_dir:
            return "Jogo não inicializado"

        game_file = self._data_dir / "guess_game.json"
        if not game_file.exists():
            return "Jogo não inicializado. Diga 'jogo do número' para começar."

        data = json.loads(game_file.read_text(encoding="utf-8"))
        number = data["number"]
        data["attempts"] += 1
        game_file.write_text(json.dumps(data), encoding="utf-8")

        if guess < number:
            return f"📈 Maior! (Tentativa {data['attempts']})"
        elif guess > number:
            return f"📉 Menor! (Tentativa {data['attempts']})"
        else:
            result = f"🎉 Parabéns! Você acertou o número {number} em {data['attempts']} tentativas!"
            game_file.unlink()
            return result

    def roll_dice(self, sides: int = 6, count: int = 1) -> str:
        """Rola dados."""
        results = [random.randint(1, sides) for _ in range(count)]
        total = sum(results)
        if count == 1:
            return f"🎲 Resultado: {results[0]}"
        return f"🎲 Resultados: {results} (Total: {total})"

    def coin_flip(self) -> str:
        """Joga uma moeda."""
        result = random.choice(["Cara", "Coroa"])
        return f"🪙 {result}!"

    def eight_ball(self, question: str = "") -> str:
        """Bola 8 mágica."""
        responses = [
            "Sim, definitivamente!",
            "É certo.",
            "Sem dúvida.",
            "Sim.",
            "Pode contar com isso.",
            "Como eu vejo, sim.",
            "Provavelmente sim.",
            "Os sinais apontam que sim.",
            "Pergunte de novo depois.",
            "Melhor não te contar agora.",
            "Não posso prever agora.",
            "Concentre-se e pergunte de novo.",
            "Não conte com isso.",
            "Minha resposta é não.",
            "Minhas fontes dizem que não.",
            "Muito duvidoso.",
        ]
        return f"🎱 {random.choice(responses)}"

    def get_daily_card(self) -> str:
        """Retorna um 'card do dia' aleatório."""
        cards = [
            ("🚀 Foco", "Hoje é um bom dia para começar aquele projeto adiado."),
            ("📚 Aprendizado", "Reserve 30 minutos para aprender algo novo hoje."),
            ("☕ Pausa", "Lembre-se de fazer pausas regulares. Seu corpo agradece."),
            ("🎯 Meta", "Defina 3 micro-metas para hoje e execute-as."),
            ("💪 Exercício", "Uma caminhada curta pode recarregar suas ideias."),
            ("📝 Anotação", "Anotar ideias é mais eficiente do que tentar lembrar depois."),
            ("🎧 Música", "Uma playlist instrumental pode aumentar sua produtividade."),
            ("🌱 Progresso", "Mesmo pequenos passos são progresso. Continue."),
            ("🔍 Revisão", "Revise o que fez hoje. Aprendizado vem da reflexão."),
            ("🌟 Gratidão", "Agradeça por 3 coisas boas que aconteceram hoje."),
        ]
        title, message = random.choice(cards)
        return f"{title}\n{message}"
