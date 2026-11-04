# GlazeCorp Live Break-Even & Decay Rate Dashboard

Real-time quantitative radar for all 26+ Fund Tokens on [GlazeCorp](https://www.glazecorp.io/explore) (Robinhood Chain ID `4663`).

## Key Features
- **Live On-Chain Auction Sync**: Pulls live Dutch Auction `initialPrice`, `auctionStartedAt`, `tps`, AMM pool reserves (`reserveBaseRaw`, `reserveQuoteRaw`), and Treasury NAV from the Goldsky Subgraph (`glazecorp-zero-rpc/0.3.0/gn`) and `/explore`.
- **Per-Minute Decay vs. Mining Gain**: Compares exact per-minute cash refund decay (`-$Cash/min` = `2.67% of P_in/min`) against realized mined token value (`+$Token/min` after Constant-Product AMM slippage).
- **Exact Break-Even Cutoff Window (`0m -> t_BE`)**: Solves for the exact minute `t_BE` in `[0, 60]` where `CashRefund(t) + RealizedTokens(t) >= P_in`.
- **Zero-Luck Safe Entry (`P_safe`)**: Highlights tokens where `P_in <= RealizedTokens(60m)`, guaranteeing profitability across all 60 minutes even with 0 replacements.
