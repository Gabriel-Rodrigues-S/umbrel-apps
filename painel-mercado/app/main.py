import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import feeds, quotes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

NEWS_INTERVAL_SECONDS = 600
QUOTES_INTERVAL_SECONDS = 120


async def _loop(fn, interval, label):
    while True:
        try:
            await asyncio.to_thread(fn)
        except Exception:
            logger.exception("erro ao atualizar %s", label)
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    news_task = asyncio.create_task(_loop(feeds.refresh, NEWS_INTERVAL_SECONDS, "notícias"))
    quotes_task = asyncio.create_task(_loop(quotes.refresh, QUOTES_INTERVAL_SECONDS, "cotações"))
    yield
    news_task.cancel()
    quotes_task.cancel()


app = FastAPI(title="Painel Mercado", lifespan=lifespan)


@app.get("/api/news")
def api_news(category: Optional[str] = None):
    cache = feeds.get_cache()
    if category and category != "all":
        items = cache["by_cat"].get(category, [])
    else:
        items = cache["items"]
    return {
        "updated": cache["updated"],
        "sources": cache.get("sources", []),
        "categories": feeds.CATEGORY_LABELS,
        "items": items,
        "by_category": cache.get("by_cat", {}),
    }


@app.get("/api/quotes")
def api_quotes():
    return quotes.get_cache()


@app.get("/api/health")
def health():
    return {"status": "ok"}


app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
