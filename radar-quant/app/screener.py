"""Screener: uma linha por ativo (gravada em `screener`), consulta com filtros e resumo do índice."""
import threading

from app import analysis, db, service
from app.config import INDICES, MARKETS
from app.stats import factors as F
from app.stats.swing import SETUPS, pooled_evidence

SCOPES = ("watchlist", "IBOV", "IBRA", "SP500", "NDX")
VERDICTS = ("comprar", "manter", "vender")
EVIDENCES = ("favoravel", "contraria", "sem_evidencia")
NUMERIC = ("score", "price", "change_pct", "momentum", "trend", "dist_sma200", "reversal", "volatility", "drawdown")
MAX_PAGE_SIZE = 200
_MARKER = {"status": "insuficiente"}  # db.py não apaga só a linha do screener: grava-se este marcador
_cache: dict[str, tuple[tuple, dict]] = {}  # escopo -> (chave, resumo)
_lock = threading.Lock()


class ScreenerError(ValueError):
    pass


def _valid(payload: dict) -> bool:
    return payload.get("status") != _MARKER["status"]


def build_row(conn, asset: dict) -> dict | None:
    """Linha do screener (com `pool` por setup) ou None se a análise for insuficiente."""
    a = analysis.analyze_asset(conn, asset)
    if a["status"] != "ok":
        return None
    close = service.load_frame(conn, asset["id"])["close"]
    entry = db.catalog_entry(conn, asset["symbol"], asset["market"])
    factors = {f["key"]: f for f in a["factors"]}
    row = {"id": asset["id"], "symbol": asset["symbol"], "market": asset["market"],
           "name": entry["name"] if entry else None, "price": close.iloc[-1],
           "change_pct": close.iloc[-1] / close.iloc[-2] - 1 if len(close) > 1 else None,
           "score": a["score"], "verdict": a["verdict"], "evidence": a["backtest"]["evidence"],
           **{k: factors[k]["normalized"] for k in F.WEIGHTS},
           "volatility": a["volatility"], "drawdown": a["drawdown"],
           "above_sma200": (factors["dist_sma200"]["raw"] or 0) > 0,
           "setups": {s["key"]: {"state": s["state"], "evidence": s["stats"]["evidence"]}
                      for s in a["swing"]["setups"]},
           "as_of": a["as_of"], "pool": analysis.swing_pool(conn, asset)}
    return analysis.clean(row)


def store_row(conn, asset: dict) -> bool:
    """Grava a linha; análise insuficiente troca a linha anterior pelo marcador. Devolve se gravou linha."""
    row = build_row(conn, asset)
    if row is None:
        db.upsert_screener(conn, asset["id"], "", _MARKER)
        return False
    db.upsert_screener(conn, asset["id"], row["as_of"], row)
    return True


def _check_scope(scope: str) -> None:
    if scope not in SCOPES:
        raise ScreenerError(f"escopo inválido: {scope}")


def scope_assets(conn, scope: str) -> list[dict]:
    _check_scope(scope)
    if scope == "watchlist":
        return db.list_assets(conn, watch=True)
    members = {(m["symbol"], m["market"]) for m in db.index_members(conn, scope)}
    return [a for a in db.list_assets(conn, watch=None) if (a["symbol"], a["market"]) in members]


def progress(conn, scope: str) -> dict:
    assets = scope_assets(conn, scope)
    total = len(assets) if scope == "watchlist" else len(db.index_members(conn, scope))
    ready = sum(_valid(r["payload"]) for r in db.load_screener(conn, [a["id"] for a in assets]))
    return {"scope": scope, "total": total, "ready": ready}


def _scope_rows(conn, scope: str) -> list[dict]:
    """Registros gravados do escopo (payload + updated_at) sem o marcador; watchlist completa o que falta."""
    assets = scope_assets(conn, scope)
    stored = db.load_screener(conn, [a["id"] for a in assets])
    if scope == "watchlist":
        have = {r["asset_id"] for r in stored}
        todo = [a for a in assets if a["id"] not in have and a["last_refresh"] and not a["last_error"]]
        for a in todo:
            store_row(conn, a)
        if todo:
            stored = db.load_screener(conn, [a["id"] for a in assets])
    return [r for r in stored if _valid(r["payload"])]


def _updated_at(recs: list[dict]) -> str | None:
    return max((r["updated_at"] for r in recs), default=None)


def query(conn, scope="watchlist", market=None, verdict=None, evidence=None, setup=None,
          sort="score", order="desc", page=1, page_size=50) -> dict:
    _check_scope(scope)
    for name, value, allowed in (("market", market, MARKETS), ("verdict", verdict, VERDICTS),
                                 ("evidence", evidence, EVIDENCES), ("setup", setup, tuple(SETUPS))):
        if value is not None and value not in allowed:
            raise ScreenerError(f"{name} inválido: {value}")
    if sort != "symbol" and sort not in NUMERIC:
        raise ScreenerError(f"sort inválido: {sort}")
    if order not in ("asc", "desc"):
        raise ScreenerError(f"order inválido: {order}")
    if page < 1 or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ScreenerError(f"paginação inválida: page={page}, page_size={page_size} (máx. {MAX_PAGE_SIZE})")
    recs = _scope_rows(conn, scope)
    rows = [r["payload"] for r in recs]
    rows = [r for r in rows
            if (market is None or r["market"] == market) and (verdict is None or r["verdict"] == verdict)
            and (evidence is None or r["evidence"] == evidence)
            and (setup is None or r["setups"][setup]["state"] in ("sinal", "posicao"))]
    rows.sort(key=lambda r: r["symbol"])  # desempate estável por símbolo
    have = [r for r in rows if r.get(sort) is not None]
    have.sort(key=lambda r: r[sort], reverse=order == "desc")
    rows = have + [r for r in rows if r.get(sort) is None]  # None sempre por último
    start = (page - 1) * page_size
    return {"scope": scope, "total": len(rows), "page": page, "page_size": page_size,
            "rows": [{k: v for k, v in r.items() if k != "pool"} for r in rows[start:start + page_size]],
            "updated_at": _updated_at(recs)}


def summary(conn, scope: str) -> dict:
    _check_scope(scope)
    recs = _scope_rows(conn, scope)
    key = (len(recs), _updated_at(recs))
    with _lock:
        hit = _cache.get(scope)
    if hit and hit[0] == key:
        return hit[1]
    rows = [r["payload"] for r in recs]
    n = len(rows)
    setups = []
    for k, meta in SETUPS.items():
        pool = [(m, e) for r in rows for m, e in r.get("pool", {}).get(k, [])]
        setups.append({"key": k, "label": meta["label"],
                       "active": sum(r["setups"][k]["state"] in ("sinal", "posicao") for r in rows),
                       "pooled": pooled_evidence(pool)})
    out = analysis.clean({
        "scope": scope, "count": n,
        "pct_above_sma200": sum(r["above_sma200"] for r in rows) / n if n else None,
        "verdicts": {v: sum(r["verdict"] == v for r in rows) for v in VERDICTS}, "setups": setups})
    with _lock:
        _cache[scope] = (key, out)
    return out
