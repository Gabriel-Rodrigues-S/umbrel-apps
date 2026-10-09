"""CDI diário (série SGS 12 do Banco Central) para a taxa livre de risco."""
from datetime import date, timedelta

import httpx

from .base import ProviderError

URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados"


async def fetch_cdi(transport: httpx.AsyncBaseTransport | None = None) -> list[tuple[str, float]]:
    """Devolve (data ISO, taxa diária em fração)."""
    end = date.today()
    start = end - timedelta(days=3651)  # limite da API: 10 anos (evita erro em 29/02)
    params = {"formato": "json", "dataInicial": start.strftime("%d/%m/%Y"),
              "dataFinal": end.strftime("%d/%m/%Y")}
    try:
        async with httpx.AsyncClient(transport=transport, timeout=20) as client:
            resp = await client.get(URL, params=params)
        if resp.status_code != 200:
            raise ProviderError(f"BCB: HTTP {resp.status_code}")
        out = []
        for item in resp.json():
            d, m, y = item["data"].split("/")
            out.append((f"{y}-{m}-{d}", float(item["valor"]) / 100))
        return out
    except httpx.HTTPError as e:
        raise ProviderError(f"BCB indisponível: {e}") from e
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise ProviderError(f"BCB: resposta inválida: {e!r}") from e
