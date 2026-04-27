"""
Telegram notifications with optional SOCKS5 proxy support.
"""
import os
import requests
from logger import log


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, proxy: str = ""):
        self.token   = token
        self.chat_id = chat_id
        self.url     = f"https://api.telegram.org/bot{token}/sendMessage"
        self.proxies = {}
        if proxy:
            self.proxies = {"https": proxy, "http": proxy}

    def send(self, text: str) -> None:
        if not self.token or not self.chat_id:
            return
        try:
            resp = requests.post(
                self.url,
                json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
                proxies=self.proxies,
                timeout=10,
            )
            if not resp.ok:
                log.warning(f"Telegram send failed: {resp.text}")
        except Exception as e:
            log.warning(f"Telegram error: {e}")

    def signal(
        self,
        symbol:    str,
        direction: str,
        entry:     float,
        tp:        float,
        sl:        float,
        qty:       float,
        rr:        float,
        atr:       float,
        reason:    str = "",
        mode:      str = "RELAXED",
    ) -> None:
        """Send signal notification with MODE indicator."""
        emoji = "🟢 LONG" if direction == "Buy" else "🔴 SHORT"
        
        # Mode emoji and text
        if mode == "STRICT":
            mode_emoji = "🔥"
            mode_text = "STRICT MODE 🔥"
        elif mode == "RELAXED":
            mode_emoji = "⚡"
            mode_text = "RELAXED MODE ⚡"
        else:
            mode_emoji = "📊"
            mode_text = "CLASSIC MODE 📊"
        
        sl_pct = abs(entry - sl) / entry * 100
        tp_pct = abs(tp - entry) / entry * 100
        
        msg = (
            f"<b>{emoji} {symbol}</b> {mode_emoji}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎯 <b>{mode_text}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📍 Entry:  <code>{entry:.4f}</code>\n"
            f"🎯 TP:     <code>{tp:.4f}</code>  (+{tp_pct:.2f}%)\n"
            f"🛑 SL:     <code>{sl:.4f}</code>  (-{sl_pct:.2f}%)\n"
            f"📊 RR:     <code>1:{rr:.1f}</code>\n"
            f"📦 Qty:    <code>{qty}</code>\n"
            f"📈 ATR:    <code>{atr:.4f}</code>\n"
        )
        if reason:
            msg += f"💡 {reason}\n"
        self.send(msg)

    def closed(self, symbol: str, direction: str, pnl: float, reason: str) -> None:
        emoji = "✅" if pnl >= 0 else "❌"
        msg = (
            f"{emoji} <b>CLOSED {symbol}</b>\n"
            f"Direction: {direction}\n"
            f"PnL: <code>{pnl:+.2f} USDT</code>\n"
            f"Reason: {reason}"
        )
        self.send(msg)

    def info(self, text: str) -> None:
        self.send(f"ℹ️ {text}")

    def error(self, text: str) -> None:
        self.send(f"🚨 ERROR: {text}")
