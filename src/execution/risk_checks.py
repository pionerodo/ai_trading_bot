import logging
import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Dict, List

logger = logging.getLogger(__name__)


@dataclass
class LocalRiskResult:
    allow_entry: bool
    reasons: List[str] = field(default_factory=list)
    adjusted_fields: Dict[str, float] = field(default_factory=dict)


_DEF_MIN_SL_PCT = Decimal("0.0035")
_MIN_RR = Decimal("2.0")


def _as_decimal(value) -> Decimal:
    if value is None:
        raise InvalidOperation("value is None")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _extract_entry(decision: dict) -> Decimal:
    if decision.get("entry_price") is not None:
        return _as_decimal(decision["entry_price"])
    entry_min = decision.get("entry_min_price") or decision.get("entry_min")
    entry_max = decision.get("entry_max_price") or decision.get("entry_max")
    if entry_min is not None and entry_max is not None:
        return (_as_decimal(entry_min) + _as_decimal(entry_max)) / Decimal("2")
    raise InvalidOperation("entry price missing")


def _extract_sl(decision: dict) -> Decimal:
    if decision.get("sl_price") is not None:
        return _as_decimal(decision["sl_price"])
    if decision.get("sl") is not None:
        return _as_decimal(decision["sl"])
    raise InvalidOperation("sl missing")


def _extract_tp1(decision: dict) -> Decimal:
    if decision.get("tp1_price") is not None:
        return _as_decimal(decision["tp1_price"])
    if decision.get("tp1") is not None:
        return _as_decimal(decision["tp1"])
    raise InvalidOperation("tp1 missing")


def evaluate_local_entry_risk(decision: dict) -> LocalRiskResult:
    reasons: List[str] = []
    adjusted: Dict[str, float] = {}

    try:
        entry = _extract_entry(decision)
        sl = _extract_sl(decision)
        tp1 = _extract_tp1(decision)
    except (InvalidOperation, ValueError) as exc:
        reason = f"missing or invalid fields: {exc}"
        logger.warning("Local risk reject: %s", reason)
        return LocalRiskResult(allow_entry=False, reasons=[reason], adjusted_fields={})

    try:
        side = decision.get("side") or decision.get("action")
        if side not in {"long", "short"}:
            raise InvalidOperation("side invalid")

        min_sl_dist = entry * _DEF_MIN_SL_PCT
        rr_ok = True

        if side == "long":
            if entry - sl < min_sl_dist:
                reasons.append(
                    f"SL too tight: entry {entry} sl {sl} min_dist {min_sl_dist}"
                )
            if tp1 - entry <= Decimal("0"):
                reasons.append("TP1 not above entry for long")
            else:
                rr = (tp1 - entry) / (entry - sl) if (entry - sl) > 0 else Decimal("0")
                if rr < _MIN_RR:
                    rr_ok = False
                    reasons.append(f"RR {rr:.3f} below minimum {_MIN_RR}")
        else:
            if sl - entry < min_sl_dist:
                reasons.append(
                    f"SL too tight: entry {entry} sl {sl} min_dist {min_sl_dist}"
                )
            if entry - tp1 <= Decimal("0"):
                reasons.append("TP1 not below entry for short")
            else:
                rr = (entry - tp1) / (sl - entry) if (sl - entry) > 0 else Decimal("0")
                if rr < _MIN_RR:
                    rr_ok = False
                    reasons.append(f"RR {rr:.3f} below minimum {_MIN_RR}")

        allow_entry = len(reasons) == 0 and rr_ok
        if not allow_entry:
            logger.warning("Local risk reject: %s", "; ".join(reasons))
        return LocalRiskResult(
            allow_entry=allow_entry,
            reasons=reasons,
            adjusted_fields=adjusted,
        )
    except InvalidOperation as exc:
        reason = f"invalid numeric values: {exc}"
        logger.warning("Local risk reject: %s", reason)
        return LocalRiskResult(allow_entry=False, reasons=[reason], adjusted_fields={})
