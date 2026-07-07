def expected_profit_per_trade(
    capital: float,
    risk_percent: float,
    win_rate: float,
    avg_win_percent: float,
    avg_loss_percent: float,
    fee_percent: float,
):
    """
    Parameters
    ----------
    capital : float
        Wallet balance (e.g. 200)

    risk_percent : float
        Risk per trade as percent (e.g. 2 for 2%)

    win_rate : float
        Win rate as percent (e.g. 48)

    avg_win_percent : float
        Average win move in percent (e.g. 0.82)

    avg_loss_percent : float
        Average loss move in percent (e.g. 0.30)

    fee_percent : float
        Fee per side in percent (e.g. 0.1)

    Returns
    -------
    Expected profit/loss in dollars for one trade.
    """

    # convert percentages to decimals
    risk = risk_percent / 100
    wr = win_rate / 100
    lr = 1 - wr

    avg_win = avg_win_percent / 100
    avg_loss = avg_loss_percent / 100
    fee = fee_percent / 100

    risk_amount = capital * risk

    stop_percent = avg_loss
    position_size = risk_amount / stop_percent

    net_win = position_size * (avg_win - 2 * fee)
    net_loss = position_size * (avg_loss + 2 * fee)

    expected = wr * net_win - lr * net_loss

    return expected

profit = expected_profit_per_trade(
    capital=200,
    risk_percent=2,
    win_rate=37.8,
    avg_win_percent=0.82,
    avg_loss_percent=0.12,
    fee_percent=0.1,
)

print(f"${profit:.2f} per trade")