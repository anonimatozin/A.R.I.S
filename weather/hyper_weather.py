"""Hyper Weather System do A.R.I.S.

Sistema de previsao do tempo multi-fonte.
Combina dados de multiplas APIs meteorologicas.
"""

import json
from urllib.request import urlopen, Request
from urllib.error import URLError
from urllib.parse import quote
from dataclasses import dataclass
from typing import Optional


@dataclass
class WeatherData:
    """Dados meteorológicos de uma fonte."""
    source: str
    city: str
    temperature_c: float
    feels_like_c: float
    humidity: int
    description: str
    wind_kmh: float
    condition: str


class HyperWeather:
    """Sistema de previsão multi-fonte.

    Consulta múltiplas APIs meteorológicas e consolida os resultados.
    """

    def __init__(self, api_keys: dict[str, str] | None = None) -> None:
        """Inicializa o sistema.

        Args:
            api_keys: Chaves de API para cada serviço.
                      Ex: {"openweather": "key", "weatherapi": "key"}
        """
        self._api_keys = api_keys or {}
        self._sources: list[str] = []

        # Registrar fontes disponíveis
        if self._api_keys.get("openweather"):
            self._sources.append("openweather")
        if self._api_keys.get("weatherapi"):
            self._sources.append("weatherapi")

    @property
    def available_sources(self) -> list[str]:
        """Fontes disponíveis."""
        return self._sources.copy()

    def _fetch_openweather(self, city: str) -> Optional[WeatherData]:
        """Busca dados do OpenWeatherMap."""
        key = self._api_keys.get("openweather")
        if not key:
            return None

        try:
            encoded_city = quote(city)
            url = (
                f"https://api.openweathermap.org/data/2.5/weather"
                f"?q={encoded_city}&appid={key}&units=metric&lang=pt_br"
            )
            req = Request(url, headers={"User-Agent": "ARIS-NEXUS/1.0"})
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            return WeatherData(
                source="OpenWeatherMap",
                city=data["name"],
                temperature_c=data["main"]["temp"],
                feels_like_c=data["main"]["feels_like"],
                humidity=data["main"]["humidity"],
                description=data["weather"][0]["description"],
                wind_kmh=round(data["wind"]["speed"] * 3.6, 1),
                condition=data["weather"][0]["main"],
            )
        except Exception:
            return None

    def _fetch_weatherapi(self, city: str) -> Optional[WeatherData]:
        """Busca dados do WeatherAPI."""
        key = self._api_keys.get("weatherapi")
        if not key:
            return None

        try:
            encoded_city = quote(city)
            url = (
                f"https://api.weatherapi.com/v1/current.json"
                f"?key={key}&q={encoded_city}&lang=pt"
            )
            req = Request(url, headers={"User-Agent": "ARIS-NEXUS/1.0"})
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            current = data["current"]
            return WeatherData(
                source="WeatherAPI",
                city=data["location"]["name"],
                temperature_c=current["temp_c"],
                feels_like_c=current["feelslike_c"],
                humidity=current["humidity"],
                description=current["condition"]["text"],
                wind_kmh=current["wind_kph"],
                condition=current["condition"]["text"],
            )
        except Exception:
            return None

    def fetch_all(self, city: str) -> list[WeatherData]:
        """Busca dados de todas as fontes disponíveis.

        Args:
            city: Nome da cidade.

        Returns:
            Lista de dados de cada fonte.
        """
        results = []

        if "openweather" in self._sources:
            data = self._fetch_openweather(city)
            if data:
                results.append(data)

        if "weatherapi" in self._sources:
            data = self._fetch_weatherapi(city)
            if data:
                results.append(data)

        return results

    def consolidate(self, city: str) -> dict:
        """Consolida previsões de múltiplas fontes.

        Args:
            city: Nome da cidade.

        Returns:
            Dicionário com previsão consolidada e metadados.
        """
        sources = self.fetch_all(city)

        if not sources:
            return {
                "city": city,
                "available": False,
                "message": "Nenhuma fonte meteorológica disponível.",
                "tip": "Configure OPENWEATHER_API_KEY ou WEATHERAPI_KEY no .env",
            }

        # Calcular médias
        temps = [s.temperature_c for s in sources]
        feels = [s.feels_like_c for s in sources]
        humids = [s.humidity for s in sources]
        winds = [s.wind_kmh for s in sources]

        avg_temp = sum(temps) / len(temps)
        avg_feel = sum(feels) / len(feels)
        avg_humid = sum(humids) / len(humids)
        avg_wind = sum(winds) / len(winds)

        # Verificar divergências
        temp_range = max(temps) - min(temps) if len(temps) > 1 else 0
        confidence = "Alta" if temp_range < 2 else "Média" if temp_range < 5 else "Baixa"

        return {
            "city": city,
            "available": True,
            "temperature_c": round(avg_temp, 1),
            "feels_like_c": round(avg_feel, 1),
            "humidity": round(avg_humid),
            "wind_kmh": round(avg_wind, 1),
            "description": sources[0].description,
            "sources_count": len(sources),
            "sources": [s.source for s in sources],
            "confidence": confidence,
            "temp_divergence": round(temp_range, 1),
        }

    def format_report(self, city: str) -> str:
        """Gera relatório formatado.

        Args:
            city: Nome da cidade.

        Returns:
            String com o relatório formatado.
        """
        data = self.consolidate(city)

        if not data.get("available"):
            return (
                f"Previsão para {city}\n"
                f"Status: Indisponível\n"
                f"{data.get('message', 'Sem dados')}\n"
                f"Dica: {data.get('tip', '')}"
            )

        lines = [
            f"Previsão para {data['city']}",
            f"Temperatura: {data['temperature_c']}°C (sensação {data['feels_like_c']}°C)",
            f"Condição: {data['description']}",
            f"Umidade: {data['humidity']}%",
            f"Vento: {data['wind_kmh']} km/h",
            f"Fontes: {data['sources_count']} ({', '.join(data['sources'])})",
            f"Confiabilidade: {data['confidence']}",
        ]

        if data["temp_divergence"] > 3:
            lines.append(f"Aviso: Divergência de {data['temp_divergence']}°C entre fontes")

        return "\n".join(lines)
