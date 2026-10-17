"""ARIS Gesture Trainer — configuração.

Lista de gestos, prompts de variação, limiares. Tudo local, sem internet.
"""

from pathlib import Path

DATA_DIR = Path(__file__).parent / "gesture_data"

# (id, rótulo, dinâmico?)
DEFAULT_GESTURES = [
    ("pinca", "PINÇA", False),
    ("mao_aberta", "MÃO ABERTA", False),
    ("punho", "PUNHO", False),
    ("apontar", "APONTAR", False),
    ("dois_dedos", "DOIS DEDOS", False),
    ("ok", "OK", False),
    ("polegar", "POLEGAR", False),
    ("deslizar_esquerda", "DESLIZAR PARA ESQUERDA", True),
    ("deslizar_direita", "DESLIZAR PARA DIREITA", True),
    ("deslizar_cima", "DESLIZAR PARA CIMA", True),
    ("deslizar_baixo", "DESLIZAR PARA BAIXO", True),
    ("girar", "GIRAR", True),
    ("aproximar", "APROXIMAR", True),
    ("afastar", "AFASTAR", True),
]

BOTH_HANDS_GESTURES = [
    ("expandir", "EXPANSÃO (2 mãos)", True),
    ("aproximar_maos", "APROXIMAR AS MÃOS", True),
    ("pinca_dupla", "PINÇA COM DUAS MÃOS", False),
    ("rotacao_dupla", "ROTAÇÃO (2 mãos)", True),
]

# Mapeamento gesto -> ação ARIS (integração futura, §18)
GESTURE_ACTIONS = {
    "pinca": "selecionar objeto",
    "mao_aberta": "cancelar",
    "dois_dedos": "modo de interação",
    "girar": "girar objeto 3D",
    "afastar": "expandir objeto",
    "aproximar": "reduzir objeto",
}

# Variações pedidas durante o treino (§7) — tolerância a torto/inclinado
VARIATION_PROMPTS = [
    "Faça novamente.",
    "Agora faça um pouco mais devagar.",
    "Agora faça um pouco mais rápido.",
    "Agora faça levemente inclinado.",
    "Agora faça mais próximo da câmera.",
    "Agora faça um pouco mais distante.",
    "Agora faça naturalmente.",
]

TARGET_SAMPLES = 300       # meta por gesto/mão (faixa 200–500)
MIN_SAMPLES = 200
SEQ_LEN = 16               # frames reamostrados p/ gestos dinâmicos
MIN_CONFIDENCE = 0.60
COOLDOWN_S = 1.0
