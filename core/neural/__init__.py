"""Neural Core do A.R.I.S.

Arquitetura cognitiva híbrida: percepção, atenção, memória, contexto,
raciocínio, decisão, segurança, ação, feedback, planejamento e
aprendizado orientados a eventos.
"""

__all__ = ["NeuralCore"]


def __getattr__(name: str):
    if name == "NeuralCore":
        from core.neural.core import NeuralCore
        return NeuralCore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
