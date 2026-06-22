"""
src/data/drawer/backtest_draw.py
TradingView-style interactive backtest chart.
Draw last backtest resault


Public API:
  draw_chart(timeframe, output_html)
"""

from __future__ import annotations
import sqlite3
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import config

# ── TradingView dark palette ──────────────────────────────────────────────────
_BG    = "#131722"   # پس‌زمینه کل
_PANEL = "#1e222d"   # پس‌زمینه tooltip / باکس‌ها
_GRID  = "#1c2030"   # خطوط گرید
_TEXT  = "#d1d4dc"   # متن اصلی
_DIM   = "#787b86"   # متن کم‌رنگ (تیک محور، stats)
_BULL  = "#26a69a"   # سبز صعودی
_BEAR  = "#ef5350"   # قرمز نزولی
_SL    = "#f23645"   # Stop Loss
_TP    = "#089981"   # Take Profit
_CROSS = "#9b9ea4"   # رنگ crosshair
_LAST  = "#b2b5be"   # آخرین قیمت (خط افقی)


# ─────────────────────────────────────────────────────────────────────────────
def _load_candles(timeframe: str) -> pd.DataFrame:
    with sqlite3.connect(config.DB_FILE) as conn:
        df = pd.read_sql("""
            SELECT Timestamp, Open, High, Low, Close, Volume
            FROM historical_candels
            WHERE Timeframe = ?
            ORDER BY Timestamp ASC
        """, conn, params=(timeframe,))
    df["time"] = pd.to_datetime(df["Timestamp"], unit="s")
    return df


def _load_positions() -> pd.DataFrame:
    with sqlite3.connect(config.DB_FILE) as conn:
        df = pd.read_sql("""
            SELECT id, position, status,
                   entry, stop_loss, take_profit,
                   exit_price, pnl_pct,
                   entry_timestamp, exit_timestamp
            FROM back_test_position
            ORDER BY entry_timestamp ASC
        """, conn)
    df["entry_time"] = pd.to_datetime(df["entry_timestamp"], unit="s")
    df["exit_time"]  = pd.to_datetime(df["exit_timestamp"],  unit="s", errors="coerce")
    return df


def _stats_text(df: pd.DataFrame) -> str:
    """یک خط خلاصه آماری برای annotation بالای چارت."""
    n = len(df)
    if n == 0:
        return "No trades"
    wins     = int((df["status"] == "TP").sum())
    losses   = n - wins
    wr       = wins / n * 100
    total    = df["pnl_pct"].dropna().sum()
    avg_w    = df.loc[df["status"] == "TP",  "pnl_pct"].mean()
    avg_l    = df.loc[df["status"] != "TP",  "pnl_pct"].mean()
    avg_w_s  = f"{avg_w:+.2f}%" if pd.notna(avg_w)  else "—"
    avg_l_s  = f"{avg_l:+.2f}%" if pd.notna(avg_l)  else "—"
    return (
        f"Trades: {n}  |  W {wins}  L {losses}  "
        f"WR {wr:.1f}%  |  "
        f"Total PnL: {total:+.2f}%  |  "
        f"Avg Win: {avg_w_s}   Avg Loss: {avg_l_s}"
    )


# ─────────────────────────────────────────────────────────────────────────────
def draw_chart(
    timeframe: str   = config.TRADING_TIME_FRAME,
    output_html: str = "backtest_chart.html",
) -> None:

    df_c = _load_candles(timeframe)
    df_p = _load_positions()

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        row_heights=[0.8, 0.2],
        vertical_spacing=0.01,
    )

    # ══════════════════════════════════════════════════════════════════════════
    # CANDLESTICKS
    # xhoverformat → زمان دقیق با ساعت:دقیقه در tooltip
    # ══════════════════════════════════════════════════════════════════════════
    fig.add_trace(go.Candlestick(
        x     = df_c["time"],
        open  = df_c["Open"],
        high  = df_c["High"],
        low   = df_c["Low"],
        close = df_c["Close"],
        name  = "Price",
        increasing  = dict(line=dict(color=_BULL, width=1), fillcolor=_BULL),
        decreasing  = dict(line=dict(color=_BEAR, width=1), fillcolor=_BEAR),
        whiskerwidth = 0,
        xhoverformat = "%Y-%m-%d  %H:%M",      # ← زمان دقیق در hover
        hoverlabel   = dict(
            bgcolor    = _PANEL,
            font_color = _TEXT,
            font_size  = 12,
        ),
    ), row=1, col=1)

    # ══════════════════════════════════════════════════════════════════════════
    # VOLUME
    # ══════════════════════════════════════════════════════════════════════════
    vol_colors = [
        _BULL if c >= o else _BEAR
        for o, c in zip(df_c["Open"], df_c["Close"])
    ]
    fig.add_trace(go.Bar(
        x            = df_c["time"],
        y            = df_c["Volume"],
        marker_color = vol_colors,
        opacity      = 0.7,
        showlegend   = False,
        hovertemplate = (
            "<b>%{x|%Y-%m-%d  %H:%M}</b><br>"
            "Volume: %{y:,.0f}"
            "<extra></extra>"
        ),
        hoverlabel = dict(bgcolor=_PANEL, font_color=_TEXT, font_size=11),
    ), row=2, col=1)

    # ══════════════════════════════════════════════════════════════════════════
    # POSITIONS
    # ══════════════════════════════════════════════════════════════════════════
    for _, pos in df_p.iterrows():
        is_long   = pos["position"] == "LONG"
        is_tp     = pos["status"]   == "TP"
        e_color   = _BULL if is_long else _BEAR
        x_color   = _TP   if is_tp   else _SL
        e_sym     = "triangle-up" if is_long else "triangle-down"
        pos_label = pos["position"]

        etime = pos["exit_time"]  if pd.notna(pos["exit_time"])  else None
        epx   = pos["exit_price"] if pd.notna(pos["exit_price"]) else None
        pnl   = pos["pnl_pct"]    if pd.notna(pos["pnl_pct"])    else None

        # ─── Entry marker ────────────────────────────────────────────────────
        fig.add_trace(go.Scatter(
            x    = [pos["entry_time"]],
            y    = [pos["entry"]],
            mode = "markers",
            marker = dict(
                symbol = e_sym,
                size   = 14,
                color  = e_color,
                line   = dict(width=1, color="white"),
            ),
            showlegend = False,
            hovertemplate = (
                f"<b>ENTRY · {pos_label} #{int(pos['id'])}</b><br>"
                f"🕐 {pos['entry_time'].strftime('%Y-%m-%d  %H:%M')}<br>"
                f"Price  :  {pos['entry']:>12,.2f}<br>"
                f"SL     :  {pos['stop_loss']:>12,.2f}<br>"
                f"TP     :  {pos['take_profit']:>12,.2f}<br>"
                "<extra></extra>"
            ),
            hoverlabel = dict(
                bgcolor     = _PANEL,
                font_color  = _TEXT,
                font_size   = 12,
                font_family = "monospace",
            ),
        ), row=1, col=1)

        # ─── Exit marker ─────────────────────────────────────────────────────
        if etime is not None and epx is not None:
            pnl_str    = f"{pnl:+.2f}%" if pnl is not None else "—"
            status_tag = "✅ TP" if is_tp else "❌ SL"
            fig.add_trace(go.Scatter(
                x    = [etime],
                y    = [epx],
                mode = "markers+text",      # ← PnL% مستقیم روی چارت
                marker = dict(
                    symbol = "x",
                    size   = 12,
                    color  = x_color,
                    line   = dict(width=2, color="white"),
                ),
                text         = [pnl_str],
                textposition = "top center",
                textfont     = dict(size=9, color=x_color, family="Arial"),
                showlegend   = False,
                hovertemplate = (
                    f"<b>EXIT · {status_tag} #{int(pos['id'])}</b><br>"
                    f"🕐 {etime.strftime('%Y-%m-%d  %H:%M')}<br>"
                    f"Price  :  {epx:>12,.2f}<br>"
                    f"PnL    :  {pnl_str}<br>"
                    "<extra></extra>"
                ),
                hoverlabel = dict(
                    bgcolor     = _PANEL,
                    font_color  = _TEXT,
                    font_size   = 12,
                    font_family = "monospace",
                ),
            ), row=1, col=1)

            # ─── Connector line ───────────────────────────────────────────────
            fig.add_trace(go.Scatter(
                x    = [pos["entry_time"], etime],
                y    = [pos["entry"],      epx],
                mode = "lines",
                line = dict(color=x_color, width=1, dash="dot"),
                showlegend = False,
                hoverinfo  = "skip",
            ), row=1, col=1)

        # ─── SL line ─────────────────────────────────────────────────────────
        if etime is not None:
            fig.add_trace(go.Scatter(
                x    = [pos["entry_time"], etime],
                y    = [pos["stop_loss"]]  * 2,
                mode = "lines",
                line = dict(color=_SL, width=1, dash="dash"),
                showlegend = False,
                hoverinfo  = "skip",
            ), row=1, col=1)

        # ─── TP line ─────────────────────────────────────────────────────────
        if etime is not None:
            fig.add_trace(go.Scatter(
                x    = [pos["entry_time"], etime],
                y    = [pos["take_profit"]] * 2,
                mode = "lines",
                line = dict(color=_TP, width=1, dash="dash"),
                showlegend = False,
                hoverinfo  = "skip",
            ), row=1, col=1)

    # ══════════════════════════════════════════════════════════════════════════
    # LAST PRICE LINE  (خط آخرین قیمت با label سمت راست)
    # ══════════════════════════════════════════════════════════════════════════
    last_close = float(df_c["Close"].iloc[-1])
    fig.add_hline(
        y                      = last_close,
        line_dash              = "dot",
        line_color             = _LAST,
        line_width             = 1,
        annotation_text        = f"  {last_close:,.2f}",
        annotation_position    = "right",
        annotation_font_color  = "white",
        annotation_font_size   = 11,
        annotation_bgcolor     = _PANEL,
        annotation_bordercolor = _LAST,
        annotation_borderwidth = 1,
        row=1, col=1,
    )

    # ══════════════════════════════════════════════════════════════════════════
    # STATS ANNOTATION  (آمار کلی بالای چارت)
    # ══════════════════════════════════════════════════════════════════════════
    fig.add_annotation(
        xref     = "paper", yref = "paper",
        x        = 0.01,    y    = 0.985,
        xanchor  = "left",  yanchor = "top",
        text     = _stats_text(df_p),
        showarrow = False,
        font      = dict(color=_DIM, size=11, family="Arial"),
        align     = "left",
    )

    # ══════════════════════════════════════════════════════════════════════════
    # LAYOUT
    # ══════════════════════════════════════════════════════════════════════════

    # تنظیمات مشترک crosshair برای محورهای X
    _spike_x = dict(
        showspikes    = True,
        spikemode     = "across+marker",   # خط عمودی + نشانگر روی محور
        spikesnap     = "cursor",
        spikecolor    = _CROSS,
        spikethickness = 1,
        spikedash     = "solid",
    )

    # تنظیمات مشترک crosshair برای محورهای Y
    _spike_y = dict(
        showspikes    = True,
        spikemode     = "across",          # خط افقی
        spikesnap     = "cursor",
        spikecolor    = _CROSS,
        spikethickness = 1,
        spikedash     = "solid",
    )

    fig.update_layout(
        # ── عنوان ──────────────────────────────────────────────────────────
        title = dict(
            text    = f"<b>{config.SYMBOL_DISPLAY}</b>  ·  {timeframe}  ·  Backtest",
            font    = dict(color=_TEXT, size=15, family="Arial"),
            x       = 0.01,
            xanchor = "left",
        ),

        template       = "plotly_dark",
        paper_bgcolor  = _BG,
        plot_bgcolor   = _BG,
        height         = 900,
        showlegend     = False,
        font           = dict(color=_TEXT, family="Arial"),
        margin         = dict(l=10, r=90, t=65, b=10),

        # ── Crosshair ── hovermode="x" → اسپایک روی هر دو پنل هماهنگ ──────
        hovermode    = "x",
        hoverdistance = 50,
        spikedistance = -1,    # ← -1 = spike تا انتهای محور کشیده می‌شود

        dragmode = "pan",      # drag = pan  |  scroll = zoom

        # ── X محور اول (پنل کندل) ──────────────────────────────────────────
        xaxis = dict(
            **_spike_x,
            type       = "date",
            showgrid   = True, gridcolor=_GRID, gridwidth=1,
            showline   = False, zeroline=False,
            tickfont   = dict(color=_DIM, size=10),
            # ── Range selector ──────────────────────────────────────────────
            rangeselector = dict(
                buttons = [
                    dict(count=6,  label="6H",  step="hour",  stepmode="backward"),
                    dict(count=1,  label="1D",  step="day",   stepmode="backward"),
                    dict(count=3,  label="3D",  step="day",   stepmode="backward"),
                    dict(count=7,  label="1W",  step="day",   stepmode="backward"),
                    dict(count=1,  label="1M",  step="month", stepmode="backward"),
                    dict(step="all", label="All"),
                ],
                bgcolor     = _PANEL,
                activecolor = _BULL,
                bordercolor = _GRID,
                font        = dict(color=_TEXT, size=10),
                x=0.5, xanchor="center", y=1.01,
            ),
            rangeslider = dict(
                visible     = True,
                thickness   = 0.03,
                bgcolor     = _PANEL,
                bordercolor = _GRID,
            ),
        ),

        # ── Y محور اول (قیمت) ─── سمت راست مثل TradingView ────────────────
        yaxis = dict(
            **_spike_y,
            side       = "right",          # ← محور قیمت سمت راست
            showgrid   = True, gridcolor=_GRID, gridwidth=1,
            showline   = False, zeroline=False,
            tickfont   = dict(color=_DIM, size=10),
            tickformat = ",.2f",           # ← فرمت دقیق قیمت روی محور
            fixedrange = False,
            automargin = True,
        ),

        # ── X محور دوم (پنل حجم) ──────────────────────────────────────────
        xaxis2 = dict(
            **_spike_x,
            type       = "date",
            showgrid   = True, gridcolor=_GRID, gridwidth=1,
            showline   = False, zeroline=False,
            tickfont   = dict(color=_DIM, size=10),
            rangeslider = dict(visible=False),
        ),

        # ── Y محور دوم (حجم) ──────────────────────────────────────────────
        yaxis2 = dict(
            **_spike_y,
            side       = "right",
            showgrid   = False,
            showline   = False, zeroline=False,
            tickfont   = dict(color=_DIM, size=9),
            tickformat = ".2s",            # ← مثلاً "1.2M" یا "450K"
            fixedrange = False,
            automargin = True,
        ),
    )

    # ══════════════════════════════════════════════════════════════════════════
    # CONFIG
    # ══════════════════════════════════════════════════════════════════════════
    plotly_config = dict(
        scrollZoom             = True,       # اسکرول موس = zoom
        displayModeBar         = True,
        modeBarButtonsToRemove = ["toImage", "sendDataToCloud"],
        displaylogo            = False,
        doubleClick            = "reset+autosize",   # دابل‌کلیک = ریست زوم
    )

    fig.write_html(output_html, config=plotly_config)
    print(f"✅  Chart saved → {output_html}")