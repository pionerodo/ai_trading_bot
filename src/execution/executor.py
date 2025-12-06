import logging
import sys

from src.db.session import SessionLocal
from src.execution.execution_loop import run_single_cycle

from src.core.config_loader import load_config
from src.execution.state_manager import load_state, save_state
from src.db.models import Order

logger = logging.getLogger(__name__)


def main(symbol: str = "BTCUSDT") -> None:
    """Thin cron-safe entrypoint that runs a single execution cycle and exits."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    try:
        run_single_cycle(db_session_factory=SessionLocal, symbol=symbol)
    except Exception:
        logger.exception("Execution cycle failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
def _get_trading_param(name: str, default: float) -> Decimal:
    value = _trading_cfg.get(name, default)
    return Decimal(str(value))


def _compute_today_realized_pnl(db: Session) -> Decimal:
    """
    Суммируем реализованный PnL за текущие сутки по записям orders,
    где json_data содержит pnl (Fallback для симуляции).
    """
    now = datetime.now(timezone.utc)
    start_of_day = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)

    q = db.query(Order).filter(Order.created_at >= start_of_day)

    total = Decimal("0")
    for row in q:
        jd = getattr(row, "json_data", None) or {}
        pnl = jd.get("pnl")
        if pnl is not None:
            total += Decimal(str(pnl))
    return total


def _is_decision_stale(decision: dict, max_age_sec: int = 600) -> bool:
    ts_iso = decision.get("timestamp_iso") or decision.get("timestamp")
    if not ts_iso:
        return True
    try:
        ts = datetime.fromisoformat(str(ts_iso).replace("Z", "+00:00"))
    except Exception:
        return True
    age_sec = (datetime.now(timezone.utc) - ts).total_seconds()
    return age_sec > max_age_sec


def _log_execution(
    db: Session,
    symbol: str,
    side: str,
    price: float,
    qty: float,
    kind: str,
    pnl: Decimal | None = None,
) -> None:
    """
    Записываем исполнение в orders как FILLED, соответствуя схеме orders/trades.
    """
    json_data: Dict[str, Any] = {"type": kind}
    if pnl is not None:
        json_data["pnl"] = float(pnl)

    now_dt = datetime.now(timezone.utc)
    client_id = f"sim_{kind}_{int(now_dt.timestamp())}"

    row = Order(
        binance_order_id=None,
        client_order_id=client_id,
        symbol=symbol,
        side="BUY" if side.upper() == "LONG" else "SELL",
        type="MARKET",
        time_in_force="GTC",
        decision_id=None,
        position_id=None,
        status="FILLED",
        created_at_exchange=now_dt,
        updated_at_exchange=now_dt,
        price=Decimal(str(price)),
        orig_qty=Decimal(str(qty)),
        executed_qty=Decimal(str(qty)),
        cumulative_quote=Decimal(str(float(price) * float(qty))),
        is_entry=1 if kind == "open" else 0,
        is_sl=1 if kind == "sl" else 0,
        is_tp=1 if kind == "close" and pnl and pnl > 0 else 0,
        created_at=now_dt,
        updated_at=now_dt,
        json_data=json_data,
    )
    db.add(row)
    db.commit()


def execute_decision(db: Session, decision: dict, price: float):
    """
    Ужесточённый исполнителЬ (без Binance):
    - учитывает risk.level и confidence из decision;
    - ограничивает риск на сделку;
    - учитывает дневной лимит потерь;
    - ведёт виртуальный equity, SL/TP и историю сделок.
    """
    symbol = decision.get("symbol", "BTCUSDT")

    state = load_state(db)
    position = state.get("position", "NONE") or "NONE"

    equity = Decimal(str(state.get("equity", 0) or 0))
    qty_current = Decimal(str(state.get("qty", 0) or 0))
    price_dec = Decimal(str(price))

    action = str(decision.get("action", "flat")).upper()
    confidence = float(decision.get("confidence", 0.0) or 0.0)
    risk_level = int(decision.get("risk_level", 1) or 0)
    risk_checks = decision.get("risk_checks") or {}
    entry_zone = decision.get("entry_zone") or []

    # ---- параметры риска из конфига ----
    max_risk_pct = _get_trading_param("max_risk_pct_per_trade", 0.01)
    max_daily_loss_pct = _get_trading_param("max_daily_loss_pct", 0.05)
    position_cap_usd = _get_trading_param("position_size_cap_usd", 5000.0)
    assumed_stop_pct = _get_trading_param("assumed_stop_pct", 0.01)

    now_ms = _now_ms()

    # ---- дневной PnL и лимит просадки ----
    today_pnl = _compute_today_realized_pnl(db)
    equity_start_today = equity - today_pnl

    daily_loss_pct = Decimal("0")
    if equity_start_today > 0 and today_pnl < 0:
        daily_loss_pct = (-today_pnl) / equity_start_today

    hard_daily_risk_off = daily_loss_pct > max_daily_loss_pct

    # ---- функции для закрытия позиции ----
    def close_position_if_any():
        nonlocal equity, position, qty_current, state

        if position == "NONE" or qty_current == 0:
            return

        entry_price_raw = state.get("entry_price")
        if entry_price_raw is None:
            # на всякий случай закрываем без PnL
            state.update(
                {
                    "position": "NONE",
                    "entry_price": None,
                    "entry_time": None,
                    "qty": 0.0,
                    "stop_loss": None,
                    "take_profit": None,
                    "equity": float(equity),
                    "updated_at": now_ms,
                }
            )
            save_state(db, state)
            position = "NONE"
            qty_current = Decimal("0")
            return

        entry_price = Decimal(str(entry_price_raw))
        side_mult = Decimal("1") if position == "LONG" else Decimal("-1")
        pnl = (Decimal(str(price)) - entry_price) * side_mult * qty_current

        equity += pnl

        _log_execution(
            db=db,
            symbol=symbol,
            side=position,
            price=float(price),
            qty=float(qty_current),
            kind="close",
            pnl=pnl,
        )

        state.update(
            {
                "position": "NONE",
                "entry_price": None,
                "entry_time": None,
                "qty": 0.0,
                "stop_loss": None,
                "take_profit": None,
                "equity": float(equity),
                "updated_at": now_ms,
            }
        )
        save_state(db, state)

        position = "NONE"
        qty_current = Decimal("0")

    # Проверка свежести решения после определения функций управления позицией
    if _is_decision_stale(decision):
        close_position_if_any()
        return

    # ---- ограничения на НОВЫЕ входы ----
    MIN_CONF = 0.6

    can_open_new = True
    if risk_level <= 0:
        can_open_new = False
    if confidence < MIN_CONF:
        can_open_new = False
    if hard_daily_risk_off:
        can_open_new = False
    if any(v is False for v in risk_checks.values()):
        can_open_new = False

    # ---- обрабатываем действие ----

    # 1) FLAT → просто закрыть позицию, новых не открываем
    if action == "FLAT":
        close_position_if_any()
        return

    desired_pos = action  # "LONG" / "SHORT"

    # 2) Если открыта противоположная позиция — закрываем её
    if position != "NONE" and position != desired_pos:
        close_position_if_any()

    # 3) Если нельзя открывать новые позиции — на этом всё
    if not can_open_new:
        return

    if entry_zone and len(entry_zone) == 2:
        lower, upper = Decimal(str(entry_zone[0])), Decimal(str(entry_zone[1]))
        if price_dec < lower * Decimal("0.995") or price_dec > upper * Decimal("1.005"):
            return

    # 4) Если уже в нужной стороне и qty > 0 — ничего не делаем
    if state.get("position") == desired_pos and qty_current > 0:
        return

    # 5) Рассчёт размера позиции от риска
    if equity <= 0:
        # без депозита не торгуем
        return

    risk_amount_usd = equity * max_risk_pct
    if risk_amount_usd <= 0:
        return

    # Какой нотацион можем позволить при заданном стопе
    notional_by_risk = risk_amount_usd / assumed_stop_pct
    target_notional = min(notional_by_risk, position_cap_usd)

    if target_notional <= 0:
        return

    qty_new = target_notional / price_dec
    # Округляем до 0.0001 BTC
    qty_new = qty_new.quantize(Decimal("0.0001"))

    if qty_new <= 0:
        return

    # 6) Открываем виртуальную позицию и сохраняем SL/TP
    decision_sl = decision.get("sl")
    decision_tp = decision.get("tp1") or decision.get("tp2")

    if decision_sl is None:
        if desired_pos == "LONG":
            decision_sl = float(Decimal(str(price)) * (Decimal("1") - assumed_stop_pct))
        else:
            decision_sl = float(Decimal(str(price)) * (Decimal("1") + assumed_stop_pct))

    if decision_tp is None:
        if desired_pos == "LONG":
            decision_tp = float(Decimal(str(price)) * (Decimal("1") + assumed_stop_pct * Decimal("2")))
        else:
            decision_tp = float(Decimal(str(price)) * (Decimal("1") - assumed_stop_pct * Decimal("2")))

    state.update(
        {
            "position": desired_pos,
            "entry_price": float(price),
            "entry_time": now_ms,
            "qty": float(qty_new),
            "stop_loss": float(decision_sl),
            "take_profit": float(decision_tp),
            "equity": float(equity),
            "updated_at": now_ms,
        }
    )
    save_state(db, state)

    _log_execution(
        db=db,
        symbol=symbol,
        side=desired_pos,
        price=float(price),
        qty=float(qty_new),
        kind="open",
    )
