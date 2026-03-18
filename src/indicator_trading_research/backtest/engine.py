"""Minimal deterministic backtest engine.

Execution rules are intentionally explicit:

- signals are generated from bar-close information only
- entry and opposite-signal exits happen on the next bar open
- a same-open flip is allowed: an opposite signal closes the current trade and can
  open the new trade on that same next bar open
- stop-loss and take-profit thresholds are derived from the adjusted entry price
- ATR-based thresholds use ATR from the signal bar close, then freeze that value
  at entry for the life of the trade
- if ATR is unavailable on the signal bar because warmup is incomplete, the signal
  is skipped only when entry-time ATR-dependent protections require it
- trailing stop updates use close-only ratcheting and are applied after current-bar
  hit checks, so a newly tightened trail only applies from the next bar onward
- ATR-based trailing distance uses live ATR on each bar when available
- ATR-based trailing activation uses ATR at entry when available
- chandelier trailing uses highest-high / lowest-low since entry with live ATR
- break-even stop activates after hit checks and competes with other stop-side
  protections using the tightest stop on each bar
- MA stop uses the strategy-provided MA series for the current bar, ratchets only
  in the favorable direction, and updates after hit checks
- MA stop requires the selected MA source to be available on the signal bar; if
  that MA is still warming up, the signal is skipped
- ATR-buffered MA stop uses live ATR on each update bar when ATR is available
- if both stop-loss and take-profit are touched within the same bar, the engine
  assumes stop-loss triggers first
- an open trade at the end of the data is forced flat on the final bar close
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from indicator_trading_research.indicators import compute_atr

from .contracts import BacktestConfig, BacktestResult, TradeRecord
from .metrics import compute_backtest_metrics

SUPPORTED_PROTECTION_MODES = {"absolute", "atr"}
SUPPORTED_ATR_METHODS = {"wilder", "sma", "ema"}
SUPPORTED_TRAILING_TYPES = {"standard", "chandelier"}
SUPPORTED_MA_STOP_SOURCES = {"short", "long"}


@dataclass
class OpenPosition:
    trade_id: str
    side: str
    entry_time: pd.Timestamp
    entry_price: float
    stop_loss: float | None
    take_profit: float | None
    atr_at_entry: float | None
    trailing_active: bool
    trailing_stop_price: float | None
    trailing_stop_initial: float | None
    trailing_stop_reason: str | None
    break_even_active: bool
    break_even_stop_price: float | None
    ma_stop_price: float | None
    ma_stop_initial: float | None
    high_since_entry: float
    low_since_entry: float
    size: float
    strategy_name: str
    entry_bar_index: int


def _execution_price(side: str, base_price: float, *, spread: float, slippage: float, is_entry: bool) -> float:
    half_spread = spread / 2.0
    if side == "long":
        return base_price + half_spread + slippage if is_entry else base_price - half_spread - slippage
    return base_price - half_spread - slippage if is_entry else base_price + half_spread + slippage


def _normalize_protection_mode(name: str, mode: str | None, value: float | None, *, allow_zero: bool = False) -> str | None:
    if value is None:
        if mode is not None:
            raise ValueError(f"{name}_mode requires {name} to be set.")
        return None

    if allow_zero:
        if value < 0:
            raise ValueError(f"{name} must be zero or positive when provided.")
    elif value <= 0:
        raise ValueError(f"{name} must be positive when provided.")

    normalized_mode = (mode or "absolute").strip().lower()
    if normalized_mode not in SUPPORTED_PROTECTION_MODES:
        supported = ", ".join(sorted(SUPPORTED_PROTECTION_MODES))
        raise ValueError(f"Unsupported {name}_mode: {mode!r}. Supported modes: {supported}.")
    return normalized_mode


def _normalize_trailing_type(value: str | None) -> str:
    normalized = (value or "standard").strip().lower()
    if normalized not in SUPPORTED_TRAILING_TYPES:
        supported = ", ".join(sorted(SUPPORTED_TRAILING_TYPES))
        raise ValueError(f"Unsupported trailing_type: {value!r}. Supported types: {supported}.")
    return normalized


def _normalize_ma_stop_source(value: str | None) -> str:
    normalized = (value or "short").strip().lower()
    if normalized not in SUPPORTED_MA_STOP_SOURCES:
        supported = ", ".join(sorted(SUPPORTED_MA_STOP_SOURCES))
        raise ValueError(f"Unsupported ma_stop_source: {value!r}. Supported sources: {supported}.")
    return normalized


def _validate_atr_settings(period: int, method: str, *, period_name: str, method_name: str) -> str:
    if not isinstance(period, int) or period <= 0:
        raise ValueError(f"{period_name} must be a positive integer.")
    normalized_method = method.strip().lower()
    if normalized_method not in SUPPORTED_ATR_METHODS:
        supported = ", ".join(sorted(SUPPORTED_ATR_METHODS))
        raise ValueError(f"Unsupported {method_name}: {method!r}. Supported methods: {supported}.")
    return normalized_method


def _validate_config(config: BacktestConfig) -> None:
    if config.fixed_position_size <= 0:
        raise ValueError("fixed_position_size must be positive.")
    if config.spread < 0:
        raise ValueError("spread must be zero or positive.")
    if config.slippage < 0:
        raise ValueError("slippage must be zero or positive.")
    if config.fee_per_trade < 0:
        raise ValueError("fee_per_trade must be zero or positive.")
    if not config.allow_long and not config.allow_short:
        raise ValueError("At least one of allow_long or allow_short must be enabled.")
    if not config.one_position_at_a_time:
        raise NotImplementedError("V1 engine supports one_position_at_a_time=True only.")

    config.stop_loss_mode = _normalize_protection_mode("stop_loss", config.stop_loss_mode, config.stop_loss)
    config.take_profit_mode = _normalize_protection_mode("take_profit", config.take_profit_mode, config.take_profit)
    config.trailing_type = _normalize_trailing_type(config.trailing_type)
    config.trailing_stop_mode = _normalize_protection_mode("trailing_stop", config.trailing_stop_mode, config.trailing_stop)
    config.trailing_activation_mode = _normalize_protection_mode("trailing_activation", config.trailing_activation_mode, config.trailing_activation)
    config.break_even_mode = _normalize_protection_mode("break_even", config.break_even_mode, config.break_even)
    if config.break_even is not None and config.break_even_buffer is None:
        config.break_even_buffer = 0.0
    config.break_even_buffer_mode = _normalize_protection_mode(
        "break_even_buffer",
        config.break_even_buffer_mode,
        config.break_even_buffer,
        allow_zero=True,
    )
    config.ma_stop_source = _normalize_ma_stop_source(config.ma_stop_source)
    if config.ma_stop:
        if config.ma_stop_buffer is None:
            config.ma_stop_buffer = 0.0
        config.ma_stop_buffer_mode = _normalize_protection_mode(
            "ma_stop_buffer",
            config.ma_stop_buffer_mode,
            config.ma_stop_buffer,
            allow_zero=True,
        )
    else:
        if config.ma_stop_buffer is not None or config.ma_stop_buffer_mode is not None:
            raise ValueError("ma_stop_buffer and ma_stop_buffer_mode require ma_stop to be enabled.")
        config.ma_stop_buffer_mode = None

    has_standard_trailing = config.trailing_type == "standard" and config.trailing_stop is not None
    has_chandelier_trailing = config.trailing_type == "chandelier" and config.chandelier_multiplier is not None
    if config.trailing_activation is not None and not (has_standard_trailing or has_chandelier_trailing):
        raise ValueError("trailing_activation requires trailing stop configuration.")
    if config.trailing_type == "standard":
        if config.chandelier_multiplier is not None:
            raise ValueError("chandelier_multiplier is only used with trailing_type='chandelier'.")
    else:
        if config.trailing_stop is not None or config.trailing_stop_mode is not None:
            raise ValueError("trailing_stop and trailing_stop_mode are not used with trailing_type='chandelier'.")
        if config.chandelier_multiplier is None or config.chandelier_multiplier <= 0:
            raise ValueError("trailing_type='chandelier' requires a positive chandelier_multiplier.")
        config.chandelier_atr_method = _validate_atr_settings(
            config.chandelier_atr_period,
            config.chandelier_atr_method,
            period_name="chandelier_atr_period",
            method_name="chandelier_atr_method",
        )

    config.atr_method = _validate_atr_settings(
        config.atr_period,
        config.atr_method,
        period_name="atr_period",
        method_name="atr_method",
    )
    uses_atr = any(
        mode == "atr"
        for mode in (
            config.stop_loss_mode,
            config.take_profit_mode,
            config.trailing_stop_mode,
            config.trailing_activation_mode,
            config.break_even_mode,
            config.break_even_buffer_mode,
            config.ma_stop_buffer_mode,
        )
    )
    if uses_atr:
        if config.stop_loss_mode == "atr" and config.stop_loss is None:
            raise ValueError("stop_loss_mode='atr' requires stop_loss to be set.")
        if config.take_profit_mode == "atr" and config.take_profit is None:
            raise ValueError("take_profit_mode='atr' requires take_profit to be set.")
        if config.trailing_stop_mode == "atr" and config.trailing_stop is None:
            raise ValueError("trailing_stop_mode='atr' requires trailing_stop to be set.")
        if config.trailing_activation_mode == "atr" and config.trailing_activation is None:
            raise ValueError("trailing_activation_mode='atr' requires trailing_activation to be set.")
        if config.break_even_mode == "atr" and config.break_even is None:
            raise ValueError("break_even_mode='atr' requires break_even to be set.")
        if config.break_even_buffer_mode == "atr" and config.break_even_buffer is None:
            raise ValueError("break_even_buffer_mode='atr' requires break_even_buffer to be set.")
        if config.ma_stop_buffer_mode == "atr" and config.ma_stop_buffer is None:
            raise ValueError("ma_stop_buffer_mode='atr' requires ma_stop_buffer to be set.")


def _effective_stop(position: OpenPosition) -> tuple[float | None, str | None]:
    candidates: list[tuple[float, str]] = []
    if position.stop_loss is not None:
        candidates.append((position.stop_loss, "stop_loss"))
    if position.break_even_stop_price is not None:
        candidates.append((position.break_even_stop_price, "break_even"))
    if position.ma_stop_price is not None:
        candidates.append((position.ma_stop_price, "ma_stop"))
    if position.trailing_stop_price is not None and position.trailing_stop_reason is not None:
        candidates.append((position.trailing_stop_price, position.trailing_stop_reason))
    if not candidates:
        return None, None
    if position.side == "long":
        return max(candidates, key=lambda item: item[0])
    return min(candidates, key=lambda item: item[0])


def _resolve_exit_from_bar(position: OpenPosition, bar: pd.Series) -> tuple[float, str] | None:
    effective_stop, stop_reason = _effective_stop(position)
    if effective_stop is None and position.take_profit is None:
        return None

    low = float(bar["low"])
    high = float(bar["high"])
    if position.side == "long":
        stop_hit = effective_stop is not None and low <= effective_stop
        take_hit = position.take_profit is not None and high >= position.take_profit
        if stop_hit and take_hit:
            return effective_stop, stop_reason or "stop_loss"
        if stop_hit:
            return effective_stop, stop_reason or "stop_loss"
        if take_hit:
            return position.take_profit, "take_profit"
    else:
        stop_hit = effective_stop is not None and high >= effective_stop
        take_hit = position.take_profit is not None and low <= position.take_profit
        if stop_hit and take_hit:
            return effective_stop, stop_reason or "stop_loss"
        if stop_hit:
            return effective_stop, stop_reason or "stop_loss"
        if take_hit:
            return position.take_profit, "take_profit"
    return None


def _compute_trade_pnl(side: str, entry_price: float, exit_price: float, size: float, fee_per_trade: float) -> tuple[float, float]:
    gross = (exit_price - entry_price) * size if side == "long" else (entry_price - exit_price) * size
    net = gross - fee_per_trade
    return gross, net


def _build_stop_take_profit(entry_price: float, side: str, config: BacktestConfig, *, atr_at_entry: float | None) -> tuple[float | None, float | None]:
    stop_loss = None
    take_profit = None

    if config.stop_loss_mode == "absolute" and config.stop_loss is not None:
        stop_distance = config.stop_loss
        stop_loss = entry_price - stop_distance if side == "long" else entry_price + stop_distance
    elif config.stop_loss_mode == "atr" and config.stop_loss is not None:
        if atr_at_entry is None or pd.isna(atr_at_entry):
            raise ValueError("ATR-based stop loss requires a non-null ATR value at entry.")
        stop_distance = config.stop_loss * atr_at_entry
        stop_loss = entry_price - stop_distance if side == "long" else entry_price + stop_distance

    if config.take_profit_mode == "absolute" and config.take_profit is not None:
        take_profit_distance = config.take_profit
        take_profit = entry_price + take_profit_distance if side == "long" else entry_price - take_profit_distance
    elif config.take_profit_mode == "atr" and config.take_profit is not None:
        if atr_at_entry is None or pd.isna(atr_at_entry):
            raise ValueError("ATR-based take profit requires a non-null ATR value at entry.")
        take_profit_distance = config.take_profit * atr_at_entry
        take_profit = entry_price + take_profit_distance if side == "long" else entry_price - take_profit_distance

    return stop_loss, take_profit


def _trailing_activation_distance(position: OpenPosition, config: BacktestConfig) -> float | None:
    if config.trailing_activation is None:
        return None
    if config.trailing_activation_mode == "absolute":
        return config.trailing_activation
    if config.trailing_activation_mode == "atr":
        if position.atr_at_entry is None or pd.isna(position.atr_at_entry):
            return None
        return config.trailing_activation * position.atr_at_entry
    return None


def _has_trailing(config: BacktestConfig) -> bool:
    if config.trailing_type == "standard":
        return config.trailing_stop is not None
    return config.chandelier_multiplier is not None


def _trailing_reason(config: BacktestConfig) -> str | None:
    if not _has_trailing(config):
        return None
    return "chandelier_trailing_stop" if config.trailing_type == "chandelier" else "trailing_stop"


def _should_activate_trailing(position: OpenPosition, bar: pd.Series, config: BacktestConfig) -> bool:
    if not _has_trailing(config) or position.trailing_active:
        return position.trailing_active
    if config.trailing_activation is None:
        return True

    activation_distance = _trailing_activation_distance(position, config)
    if activation_distance is None:
        return False

    if position.side == "long":
        return float(bar["high"]) >= position.entry_price + activation_distance
    return float(bar["low"]) <= position.entry_price - activation_distance


def _trailing_distance(config: BacktestConfig, current_atr: float | None) -> float | None:
    if config.trailing_stop is None:
        return None
    if config.trailing_stop_mode == "absolute":
        return config.trailing_stop
    if config.trailing_stop_mode == "atr":
        if current_atr is None or pd.isna(current_atr):
            return None
        return config.trailing_stop * current_atr
    return None


def _break_even_distance(position: OpenPosition, config: BacktestConfig, *, for_buffer: bool) -> float | None:
    value = config.break_even_buffer if for_buffer else config.break_even
    mode = config.break_even_buffer_mode if for_buffer else config.break_even_mode
    if value is None:
        return None
    if mode == "absolute":
        return value
    if mode == "atr":
        if position.atr_at_entry is None or pd.isna(position.atr_at_entry):
            return None
        return value * position.atr_at_entry
    return None


def _ma_stop_columns(config: BacktestConfig) -> tuple[str, str]:
    if config.ma_stop_source == "short":
        return "short_sma", "ma_fast"
    return "long_sma", "ma_slow"


def _ma_stop_value(signal_row: pd.Series, config: BacktestConfig) -> float | None:
    for column in _ma_stop_columns(config):
        if column in signal_row.index:
            value = signal_row.get(column)
            if pd.notna(value):
                return float(value)
    return None


def _ma_stop_buffer_distance(config: BacktestConfig, current_atr: float | None) -> float | None:
    value = config.ma_stop_buffer
    if value is None:
        return 0.0
    if config.ma_stop_buffer_mode == "absolute":
        return value
    if config.ma_stop_buffer_mode == "atr":
        if current_atr is None or pd.isna(current_atr):
            return None
        return value * current_atr
    return value


def _update_extrema(position: OpenPosition, bar: pd.Series) -> None:
    position.high_since_entry = max(position.high_since_entry, float(bar["high"]))
    position.low_since_entry = min(position.low_since_entry, float(bar["low"]))


def _update_break_even_stop(position: OpenPosition, bar: pd.Series, config: BacktestConfig) -> None:
    if config.break_even is None or position.break_even_active:
        return

    activation_distance = _break_even_distance(position, config, for_buffer=False)
    if activation_distance is None:
        return

    should_activate = False
    if position.side == "long":
        should_activate = float(bar["high"]) >= position.entry_price + activation_distance
    else:
        should_activate = float(bar["low"]) <= position.entry_price - activation_distance
    if not should_activate:
        return

    buffer_distance = _break_even_distance(position, config, for_buffer=True)
    if buffer_distance is None:
        return

    position.break_even_active = True
    if position.side == "long":
        position.break_even_stop_price = position.entry_price + buffer_distance
    else:
        position.break_even_stop_price = position.entry_price - buffer_distance


def _update_ma_stop(position: OpenPosition, ma_value: float | None, config: BacktestConfig, *, current_atr: float | None) -> None:
    if not config.ma_stop or ma_value is None or pd.isna(ma_value):
        return

    buffer_distance = _ma_stop_buffer_distance(config, current_atr)
    if buffer_distance is None:
        return

    candidate = ma_value - buffer_distance if position.side == "long" else ma_value + buffer_distance
    if position.side == "long":
        if position.ma_stop_price is None:
            position.ma_stop_price = candidate
            position.ma_stop_initial = candidate
        else:
            position.ma_stop_price = max(position.ma_stop_price, candidate)
    else:
        if position.ma_stop_price is None:
            position.ma_stop_price = candidate
            position.ma_stop_initial = candidate
        else:
            position.ma_stop_price = min(position.ma_stop_price, candidate)


def _chandelier_candidate(position: OpenPosition, chandelier_atr: float | None, config: BacktestConfig) -> float | None:
    if config.chandelier_multiplier is None or chandelier_atr is None or pd.isna(chandelier_atr):
        return None
    distance = config.chandelier_multiplier * chandelier_atr
    if position.side == "long":
        return position.high_since_entry - distance
    return position.low_since_entry + distance


def _update_trailing_stop(
    position: OpenPosition,
    bar: pd.Series,
    config: BacktestConfig,
    *,
    current_atr: float | None,
    chandelier_atr: float | None,
) -> None:
    if not _has_trailing(config):
        return

    if not position.trailing_active:
        position.trailing_active = _should_activate_trailing(position, bar, config)
    if not position.trailing_active:
        return

    position.trailing_stop_reason = _trailing_reason(config)
    if config.trailing_type == "chandelier":
        candidate = _chandelier_candidate(position, chandelier_atr, config)
        if candidate is None:
            return
    else:
        distance = _trailing_distance(config, current_atr)
        if distance is None:
            return
        close_price = float(bar["close"])
        candidate = close_price - distance if position.side == "long" else close_price + distance

    if position.side == "long":
        if position.trailing_stop_price is None:
            position.trailing_stop_price = candidate
            position.trailing_stop_initial = candidate
        else:
            position.trailing_stop_price = max(position.trailing_stop_price, candidate)
    else:
        if position.trailing_stop_price is None:
            position.trailing_stop_price = candidate
            position.trailing_stop_initial = candidate
        else:
            position.trailing_stop_price = min(position.trailing_stop_price, candidate)


def _finalize_trade(position: OpenPosition, exit_time: pd.Timestamp, exit_price: float, exit_reason: str, config: BacktestConfig, exit_bar_index: int) -> TradeRecord:
    gross_pnl, net_pnl = _compute_trade_pnl(position.side, position.entry_price, exit_price, position.size, config.fee_per_trade)
    outcome = "win" if net_pnl > 0 else "loss" if net_pnl < 0 else "breakeven"
    return TradeRecord(
        trade_id=position.trade_id,
        pair=config.pair,
        timeframe=config.timeframe,
        side=position.side,
        entry_time=position.entry_time,
        entry_price=position.entry_price,
        exit_time=exit_time,
        exit_price=exit_price,
        stop_loss=position.stop_loss,
        take_profit=position.take_profit,
        size=position.size,
        pnl=net_pnl,
        outcome=outcome,
        strategy_name=config.strategy_name,
        notes=None,
        atr_at_entry=position.atr_at_entry,
        trailing_stop_initial=position.trailing_stop_initial,
        trailing_stop_final=position.trailing_stop_price,
        trailing_stop_exit_hit=exit_reason in {"trailing_stop", "chandelier_trailing_stop"},
        break_even_stop_price=position.break_even_stop_price,
        break_even_exit_hit=exit_reason == "break_even",
        ma_stop_initial=position.ma_stop_initial,
        ma_stop_final=position.ma_stop_price,
        ma_stop_exit_hit=exit_reason == "ma_stop",
        exit_reason=exit_reason,
        duration_bars=exit_bar_index - position.entry_bar_index,
        gross_pnl=gross_pnl,
        net_pnl=net_pnl,
    )


def run_backtest(candles: pd.DataFrame, signals: pd.DataFrame, config: BacktestConfig) -> BacktestResult:
    if candles.empty:
        raise ValueError("Cannot backtest an empty candle dataframe.")
    if len(candles) < 2:
        raise ValueError("Need at least two bars for next-bar execution.")
    _validate_config(config)
    needs_atr = any(
        mode == "atr"
        for mode in (
            config.stop_loss_mode,
            config.take_profit_mode,
            config.trailing_stop_mode,
            config.trailing_activation_mode,
            config.break_even_mode,
            config.break_even_buffer_mode,
            config.ma_stop_buffer_mode,
        )
    )
    atr_series = compute_atr(candles, period=config.atr_period, method=config.atr_method) if needs_atr else None
    needs_chandelier_atr = config.trailing_type == "chandelier" and config.chandelier_multiplier is not None
    chandelier_atr_series = (
        compute_atr(candles, period=config.chandelier_atr_period, method=config.chandelier_atr_method)
        if needs_chandelier_atr
        else None
    )
    requires_atr_at_entry = any(
        mode == "atr"
        for mode in (
            config.stop_loss_mode,
            config.take_profit_mode,
            config.trailing_activation_mode,
            config.break_even_mode,
            config.break_even_buffer_mode,
        )
    )

    signal_frame = signals.copy()
    signal_frame["timestamp"] = pd.to_datetime(signal_frame["timestamp"], utc=True)
    signal_frame = signal_frame.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
    candles_frame = candles.copy().reset_index(drop=True)
    candles_frame["timestamp"] = pd.to_datetime(candles_frame["timestamp"], utc=True)
    signal_frame = candles_frame[["timestamp"]].merge(signal_frame, on="timestamp", how="left")
    if "signal" not in signal_frame.columns:
        signal_frame["signal"] = 0
    signal_frame["signal"] = signal_frame["signal"].fillna(0).astype(int)

    if config.ma_stop:
        preferred_column, fallback_column = _ma_stop_columns(config)
        if preferred_column not in signal_frame.columns and fallback_column not in signal_frame.columns:
            raise ValueError(
                "ma_stop requires strategy signals to include "
                f"'{preferred_column}' or '{fallback_column}' for source '{config.ma_stop_source}'."
            )
    else:
        preferred_column = None
        fallback_column = None

    realized_equity = float(config.initial_capital)
    equity_rows: list[dict[str, object]] = []
    trades: list[TradeRecord] = []
    position: OpenPosition | None = None
    trade_counter = 0

    for index in range(1, len(candles_frame)):
        previous_bar = candles_frame.iloc[index - 1]
        current_bar = candles_frame.iloc[index]
        current_time = pd.Timestamp(current_bar["timestamp"])

        previous_signal_row = signal_frame.iloc[index - 1]
        current_signal_row = signal_frame.iloc[index]
        signal_value = int(previous_signal_row.get("signal", 0))

        if position is not None:
            wants_opposite = (position.side == "long" and signal_value < 0) or (position.side == "short" and signal_value > 0)
            if wants_opposite:
                exit_price = _execution_price(position.side, float(current_bar["open"]), spread=config.spread, slippage=config.slippage, is_entry=False)
                trade = _finalize_trade(position, current_time, exit_price, "signal_exit", config, index)
                trades.append(trade)
                realized_equity += float(trade.net_pnl or 0.0)
                position = None

        can_enter_long = signal_value > 0 and config.allow_long
        can_enter_short = signal_value < 0 and config.allow_short
        if position is None and (can_enter_long or can_enter_short):
            atr_at_signal = None
            if atr_series is not None:
                atr_at_signal = float(atr_series.iloc[index - 1]) if pd.notna(atr_series.iloc[index - 1]) else None
            ma_at_signal = _ma_stop_value(previous_signal_row, config) if preferred_column is not None else None
            if (not requires_atr_at_entry or atr_at_signal is not None) and (preferred_column is None or ma_at_signal is not None):
                side = "long" if can_enter_long else "short"
                trade_counter += 1
                entry_price = _execution_price(side, float(current_bar["open"]), spread=config.spread, slippage=config.slippage, is_entry=True)
                stop_loss, take_profit = _build_stop_take_profit(entry_price, side, config, atr_at_entry=atr_at_signal)
                position = OpenPosition(
                    trade_id=f"{config.strategy_name}_{trade_counter}",
                    side=side,
                    entry_time=current_time,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    atr_at_entry=atr_at_signal,
                    trailing_active=_has_trailing(config) and config.trailing_activation is None,
                    trailing_stop_price=None,
                    trailing_stop_initial=None,
                    trailing_stop_reason=_trailing_reason(config),
                    break_even_active=False,
                    break_even_stop_price=None,
                    ma_stop_price=None,
                    ma_stop_initial=None,
                    high_since_entry=float(current_bar["high"]),
                    low_since_entry=float(current_bar["low"]),
                    size=config.fixed_position_size,
                    strategy_name=config.strategy_name,
                    entry_bar_index=index,
                )

        if position is not None:
            intrabar_exit = _resolve_exit_from_bar(position, current_bar)
            if intrabar_exit is not None:
                raw_exit_price, exit_reason = intrabar_exit
                adjusted_exit = _execution_price(position.side, raw_exit_price, spread=config.spread, slippage=config.slippage, is_entry=False)
                trade = _finalize_trade(position, current_time, adjusted_exit, exit_reason, config, index)
                trades.append(trade)
                realized_equity += float(trade.net_pnl or 0.0)
                position = None
            else:
                _update_extrema(position, current_bar)
                _update_break_even_stop(position, current_bar, config)
                current_atr = float(atr_series.iloc[index]) if atr_series is not None and pd.notna(atr_series.iloc[index]) else None
                current_ma = _ma_stop_value(current_signal_row, config) if preferred_column is not None else None
                _update_ma_stop(position, current_ma, config, current_atr=current_atr)
                chandelier_atr = (
                    float(chandelier_atr_series.iloc[index])
                    if chandelier_atr_series is not None and pd.notna(chandelier_atr_series.iloc[index])
                    else None
                )
                _update_trailing_stop(position, current_bar, config, current_atr=current_atr, chandelier_atr=chandelier_atr)

        mark_to_market = realized_equity
        if position is not None:
            unrealized = (float(current_bar["close"]) - position.entry_price) * position.size if position.side == "long" else (position.entry_price - float(current_bar["close"])) * position.size
            mark_to_market += unrealized

        equity_rows.append(
            {
                "timestamp": current_time,
                "equity": mark_to_market,
                "realized_equity": realized_equity,
                "position_side": position.side if position is not None else "flat",
            }
        )

    if position is not None:
        last_bar = candles_frame.iloc[-1]
        exit_price = _execution_price(position.side, float(last_bar["close"]), spread=config.spread, slippage=config.slippage, is_entry=False)
        final_timestamp = pd.Timestamp(last_bar["timestamp"])
        trade = _finalize_trade(position, final_timestamp, exit_price, "forced_end", config, len(candles_frame) - 1)
        trades.append(trade)
        realized_equity += float(trade.net_pnl or 0.0)
        if equity_rows:
            equity_rows[-1] = {
                "timestamp": final_timestamp,
                "equity": realized_equity,
                "realized_equity": realized_equity,
                "position_side": "flat",
            }

    trades_frame = pd.DataFrame([trade.to_dict() for trade in trades])
    if trades_frame.empty:
        trades_frame = pd.DataFrame(
            columns=[
                "trade_id",
                "pair",
                "timeframe",
                "side",
                "entry_time",
                "entry_price",
                "exit_time",
                "exit_price",
                "stop_loss",
                "take_profit",
                "size",
                "pnl",
                "outcome",
                "strategy_name",
                "notes",
                "atr_at_entry",
                "trailing_stop_initial",
                "trailing_stop_final",
                "trailing_stop_exit_hit",
                "break_even_stop_price",
                "break_even_exit_hit",
                "ma_stop_initial",
                "ma_stop_final",
                "ma_stop_exit_hit",
                "exit_reason",
                "duration_bars",
                "gross_pnl",
                "net_pnl",
            ]
        )
    equity_curve = pd.DataFrame(equity_rows)
    metrics = compute_backtest_metrics(trades_frame, equity_curve, config.initial_capital)
    return BacktestResult(
        config=config,
        trades=trades_frame,
        metrics=metrics,
        equity_curve=equity_curve,
        signals=signal_frame.reset_index(drop=True),
        candles=candles_frame,
    )
