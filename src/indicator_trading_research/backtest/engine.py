"""Minimal deterministic backtest engine."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .contracts import BacktestConfig, BacktestResult, TradeRecord
from .metrics import compute_backtest_metrics


@dataclass
class OpenPosition:
    trade_id: str
    side: str
    entry_time: pd.Timestamp
    entry_price: float
    stop_loss: float | None
    take_profit: float | None
    size: float
    strategy_name: str
    entry_bar_index: int


def _execution_price(side: str, base_price: float, *, spread: float, slippage: float, is_entry: bool) -> float:
    half_spread = spread / 2.0
    if side == "long":
        return base_price + half_spread + slippage if is_entry else base_price - half_spread - slippage
    return base_price - half_spread - slippage if is_entry else base_price + half_spread + slippage


def _resolve_exit_from_bar(position: OpenPosition, bar: pd.Series, config: BacktestConfig) -> tuple[float, str] | None:
    if position.stop_loss is None and position.take_profit is None:
        return None

    low = float(bar["low"])
    high = float(bar["high"])
    if position.side == "long":
        stop_hit = position.stop_loss is not None and low <= position.stop_loss
        take_hit = position.take_profit is not None and high >= position.take_profit
        if stop_hit and take_hit:
            return position.stop_loss, "stop_loss"
        if stop_hit:
            return position.stop_loss, "stop_loss"
        if take_hit:
            return position.take_profit, "take_profit"
    else:
        stop_hit = position.stop_loss is not None and high >= position.stop_loss
        take_hit = position.take_profit is not None and low <= position.take_profit
        if stop_hit and take_hit:
            return position.stop_loss, "stop_loss"
        if stop_hit:
            return position.stop_loss, "stop_loss"
        if take_hit:
            return position.take_profit, "take_profit"
    return None


def _compute_trade_pnl(side: str, entry_price: float, exit_price: float, size: float, fee_per_trade: float) -> tuple[float, float]:
    gross = (exit_price - entry_price) * size if side == "long" else (entry_price - exit_price) * size
    net = gross - fee_per_trade
    return gross, net


def _build_stop_take_profit(entry_price: float, side: str, config: BacktestConfig) -> tuple[float | None, float | None]:
    stop_loss = None
    take_profit = None

    if config.stop_loss_mode == "price_offset" and config.stop_loss_value is not None:
        stop_loss = entry_price - config.stop_loss_value if side == "long" else entry_price + config.stop_loss_value
    elif config.stop_loss_mode == "percent" and config.stop_loss_value is not None:
        pct = config.stop_loss_value
        stop_loss = entry_price * (1 - pct) if side == "long" else entry_price * (1 + pct)

    if config.take_profit_mode == "price_offset" and config.take_profit_value is not None:
        take_profit = entry_price + config.take_profit_value if side == "long" else entry_price - config.take_profit_value
    elif config.take_profit_mode == "percent" and config.take_profit_value is not None:
        pct = config.take_profit_value
        take_profit = entry_price * (1 + pct) if side == "long" else entry_price * (1 - pct)

    return stop_loss, take_profit


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
    if config.fixed_position_size <= 0:
        raise ValueError("fixed_position_size must be positive.")
    if not config.one_position_at_a_time:
        raise NotImplementedError("V1 engine supports one_position_at_a_time=True only.")

    signal_frame = signals.copy()
    signal_frame["timestamp"] = pd.to_datetime(signal_frame["timestamp"], utc=True)
    signal_frame = signal_frame.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
    signal_map = signal_frame.set_index("timestamp")

    realized_equity = float(config.initial_capital)
    equity_rows: list[dict[str, object]] = []
    trades: list[TradeRecord] = []
    position: OpenPosition | None = None
    trade_counter = 0

    for index in range(1, len(candles)):
        previous_bar = candles.iloc[index - 1]
        current_bar = candles.iloc[index]
        current_time = pd.Timestamp(current_bar["timestamp"])

        signal_value = 0
        if previous_bar["timestamp"] in signal_map.index:
            row = signal_map.loc[previous_bar["timestamp"]]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[-1]
            signal_value = int(row.get("signal", 0))

        if position is not None:
            wants_opposite = (position.side == "long" and signal_value < 0) or (position.side == "short" and signal_value > 0)
            if wants_opposite:
                exit_price = _execution_price(position.side, float(current_bar["open"]), spread=config.spread, slippage=config.slippage, is_entry=False)
                trade = _finalize_trade(position, current_time, exit_price, "opposite_signal", config, index)
                trades.append(trade)
                realized_equity += float(trade.net_pnl or 0.0)
                position = None

        can_enter_long = signal_value > 0 and config.allow_long
        can_enter_short = signal_value < 0 and config.allow_short
        if position is None and (can_enter_long or can_enter_short):
            side = "long" if can_enter_long else "short"
            trade_counter += 1
            entry_price = _execution_price(side, float(current_bar["open"]), spread=config.spread, slippage=config.slippage, is_entry=True)
            stop_loss, take_profit = _build_stop_take_profit(entry_price, side, config)
            position = OpenPosition(
                trade_id=f"{config.strategy_name}_{trade_counter}",
                side=side,
                entry_time=current_time,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                size=config.fixed_position_size,
                strategy_name=config.strategy_name,
                entry_bar_index=index,
            )

        if position is not None:
            intrabar_exit = _resolve_exit_from_bar(position, current_bar, config)
            if intrabar_exit is not None:
                raw_exit_price, exit_reason = intrabar_exit
                adjusted_exit = _execution_price(position.side, raw_exit_price, spread=config.spread, slippage=config.slippage, is_entry=False)
                trade = _finalize_trade(position, current_time, adjusted_exit, exit_reason, config, index)
                trades.append(trade)
                realized_equity += float(trade.net_pnl or 0.0)
                position = None

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
        last_bar = candles.iloc[-1]
        exit_price = _execution_price(position.side, float(last_bar["close"]), spread=config.spread, slippage=config.slippage, is_entry=False)
        trade = _finalize_trade(position, pd.Timestamp(last_bar["timestamp"]), exit_price, "end_of_data", config, len(candles) - 1)
        trades.append(trade)
        realized_equity += float(trade.net_pnl or 0.0)

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
        candles=candles,
    )
