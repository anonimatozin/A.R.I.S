"""Serviços do A.R.I.S.

Camada de Injeção de Dependência. Centraliza a criação e resolução
de serviços, substituindo progressivamente a God Class e a descoberta
automática por nome de classe.
"""

from core.services.container import ServiceContainer

__all__ = ["ServiceContainer"]
