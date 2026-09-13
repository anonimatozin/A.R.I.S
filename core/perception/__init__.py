"""Camada de percepção do A.R.I.S.

Sensores reais do mundo (câmera, microfone, tela, sistema, arquivos,
rede, hardware) que publicam eventos no Event Bus, onde a ponte de
atenção decide o que merece processamento, estado global e memória.

Sem dependências obrigatórias: sensores indisponíveis ficam ``offline``
e emitem zero eventos (nunca dados falsos).
"""

from core.perception.config import PerceptionConfig
from core.perception.perception_manager import PerceptionManager
from core.perception.sensor import Sensor

__all__ = ["PerceptionConfig", "PerceptionManager", "Sensor"]
