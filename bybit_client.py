"""
Bybit V5 REST client.
Handles: klines, wallet balance, set leverage, place/cancel orders,
get open positions, instrument info.
"""
import hashlib
import hmac
import time
import requests
import pandas as pd
from typing import Optional
from logger import log


class BybitClient:
    MAINNET = "https://api.bybit.com"
    TESTNET = "https://api-testnet.bybit.com"

    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self.api_key    = api_key
        self.api_secret = api_secret
        self.base_url   = self.TESTNET if testnet else self.MAINNET
        self.session    = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    # ------------------------------------------------------------------ #
    #  Signing                                                             #
    # ------------------------------------------------------------------ #
    def _sign(self, ts: str, payload: str) -> str:
        raw = f"{ts}{self.api_key}5000{payload}"
        return hmac.new(
            self.api_secret.encode(), raw.encode(), hashlib.sha256
        ).hexdigest()

    def _headers(self, ts: str, sign: str) -> dict:
        return {
            "X-BAPI-API-KEY":     self.api_key,
            "X-BAPI-TIMESTAMP":   ts,
            "X-BAPI-SIGN":        sign,
            "X-BAPI-RECV-WINDOW": "5000",
        }

    def _get(self, path: str, params: dict, retries: int = 3) -> dict:
        qs  = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        url  = self.base_url + path
        for attempt in range(1, retries + 1):
            try:
                ts   = str(int(time.time() * 1000))
                sign = self._sign(ts, qs)
                resp = self.session.get(url, params=params,
                                        headers=self._headers(ts, sign), timeout=10)
                
                # Handle rate limit
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get('Retry-After', 5))
                    log.warning(f"Rate limit hit on {path}, waiting {retry_after}s")
                    time.sleep(retry_after)
                    if attempt == retries:
                        raise RuntimeError(f"Rate limit on {path} after {retries} retries")
                    continue
                
                resp.raise_for_status()
                data = resp.json()
                if data.get("retCode") != 0:
                    raise RuntimeError(f"GET {path} error: {data.get('retMsg')}")
                
                result = data.get("result", {})
                if not isinstance(result, dict):
                    raise RuntimeError(f"Invalid result type from {path}: {type(result)}, data: {data}")
                
                return result
            except Exception as e:
                if attempt == retries:
                    raise
                log.warning(f"GET {path} attempt {attempt}/{retries} failed: {e} — retrying in 3s")
                time.sleep(3)
        raise RuntimeError(f"GET {path} failed after {retries} attempts")

    def _post(self, path: str, body: dict, retries: int = 3) -> dict:
        import json
        payload = json.dumps(body, separators=(",",":"))
        url     = self.base_url + path
        for attempt in range(1, retries + 1):
            try:
                ts   = str(int(time.time() * 1000))
                sign = self._sign(ts, payload)
                resp = self.session.post(url, data=payload,
                                         headers=self._headers(ts, sign), timeout=10)
                
                # Handle rate limit
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get('Retry-After', 5))
                    log.warning(f"Rate limit hit on {path}, waiting {retry_after}s")
                    time.sleep(retry_after)
                    if attempt == retries:
                        raise RuntimeError(f"Rate limit on {path} after {retries} retries")
                    continue
                
                resp.raise_for_status()
                data = resp.json()
                if data.get("retCode") not in (0, 110043):
                    raise RuntimeError(f"POST {path} error: {data.get('retMsg')} | body={body}")
                return data.get("result", {})
            except Exception as e:
                if attempt == retries:
                    raise
                log.warning(f"POST {path} attempt {attempt}/{retries} failed: {e} — retrying in 3s")
                time.sleep(3)
        raise RuntimeError(f"POST {path} failed after {retries} attempts")

    # ------------------------------------------------------------------ #
    #  Market data                                                         #
    # ------------------------------------------------------------------ #
    def get_klines(self, symbol: str, interval: str, limit: int = 300) -> pd.DataFrame:
        """Return OHLCV DataFrame sorted oldest→newest."""
        result = self._get("/v5/market/kline", {
            "category": "linear",
            "symbol":   symbol,
            "interval": interval,
            "limit":    limit,
        })
        rows = result.get("list", [])
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume", "turnover"])
        df = df.astype({"ts": int, "open": float, "high": float,
                        "low": float, "close": float, "volume": float})
        df.sort_values("ts", inplace=True)
        df.reset_index(drop=True, inplace=True)
        df["datetime"] = pd.to_datetime(df["ts"], unit="ms")
        return df

    def get_instrument_info(self, symbol: str) -> dict:
        """Return lotSizeFilter and priceFilter for a symbol."""
        try:
            result = self._get("/v5/market/instruments-info", {
                "category": "linear",
                "symbol":   symbol,
            })
            
            # Validate result type
            if not isinstance(result, dict):
                raise RuntimeError(f"Invalid result type: {type(result)}, expected dict")
            
            items = result.get("list", [])
            if not items:
                raise RuntimeError(f"No instrument info for {symbol}")
            
            item = items[0]
            
            # Validate item structure
            if "lotSizeFilter" not in item or "priceFilter" not in item:
                raise RuntimeError(f"Invalid instrument structure for {symbol}: {item}")
            
            return {
                "min_qty":    float(item["lotSizeFilter"]["minOrderQty"]),
                "qty_step":   float(item["lotSizeFilter"]["qtyStep"]),
                "min_price":  float(item["priceFilter"]["minPrice"]),
                "price_tick": float(item["priceFilter"]["tickSize"]),
            }
        except Exception as e:
            log.error(f"get_instrument_info failed for {symbol}: {e}")
            raise

    # ------------------------------------------------------------------ #
    #  Account                                                             #
    # ------------------------------------------------------------------ #
    def get_equity(self) -> float:
        """Return total USDT equity of unified account."""
        result = self._get("/v5/account/wallet-balance", {"accountType": "UNIFIED"})
        items  = result.get("list", [])
        if not items:
            raise RuntimeError("Empty wallet list")
        return float(items[0].get("totalEquity", 0))

    def get_open_positions(self) -> list[dict]:
        """Return list of open linear positions."""
        result = self._get("/v5/position/list", {
            "category":   "linear",
            "settleCoin": "USDT",
        })
        return [p for p in result.get("list", []) if float(p.get("size", 0)) > 0]

    # ------------------------------------------------------------------ #
    #  Trading                                                             #
    # ------------------------------------------------------------------ #
    def set_leverage(self, symbol: str, leverage: int) -> None:
        lev = str(leverage)
        self._post("/v5/position/set-leverage", {
            "category":     "linear",
            "symbol":       symbol,
            "buyLeverage":  lev,
            "sellLeverage": lev,
        })
        log.info(f"[{symbol}] Leverage set to x{leverage}")

    def place_order(
        self,
        symbol:    str,
        side:      str,   # "Buy" | "Sell"
        qty:       float,
        tp_price:  float,
        sl_price:  float,
        price_tick: float = 0.01,
    ) -> str:
        """Place market order with TP/SL. Returns orderId."""
        def fmt(p: float) -> str:
            # Round to nearest tick
            import math
            if price_tick <= 0:
                return f"{p:.8f}"
            ticks = round(p / price_tick)
            return f"{ticks * price_tick:.{max(0, -int(math.log10(price_tick)))}f}"

        body = {
            "category":    "linear",
            "symbol":      symbol,
            "side":        side,
            "orderType":   "Market",
            "qty":         str(qty),
            "takeProfit":  fmt(tp_price),
            "stopLoss":    fmt(sl_price),
            "tpslMode":    "Full",
            "tpOrderType": "Market",
            "slOrderType": "Market",
            "timeInForce": "IOC",
            "positionIdx": 0,  # one-way mode
        }
        result = self._post("/v5/order/create", body)
        return result.get("orderId", "")

    def close_position(self, symbol: str, side: str, qty: float) -> str:
        """Close position by placing opposite market order."""
        close_side = "Sell" if side == "Buy" else "Buy"
        body = {
            "category":    "linear",
            "symbol":      symbol,
            "side":        close_side,
            "orderType":   "Market",
            "qty":         str(qty),
            "reduceOnly":  True,
            "timeInForce": "IOC",
            "positionIdx": 0,
        }
        result = self._post("/v5/order/create", body)
        return result.get("orderId", "")

    def set_trading_stop(self, symbol: str, sl: float, tp: float, price_tick: float = 0.01) -> None:
        """Update SL/TP on existing position (e.g. breakeven)."""
        def fmt(p: float) -> str:
            import math
            if price_tick <= 0:
                return f"{p:.8f}"
            ticks = round(p / price_tick)
            return f"{ticks * price_tick:.{max(0, -int(math.log10(price_tick)))}f}"

        self._post("/v5/position/trading-stop", {
            "category":    "linear",
            "symbol":      symbol,
            "takeProfit":  fmt(tp),
            "stopLoss":    fmt(sl),
            "tpslMode":    "Full",
            "positionIdx": 0,
        })
