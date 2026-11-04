from http.server import BaseHTTPRequestHandler
import urllib.request
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

SUBGRAPH_URL = "https://api.goldsky.com/api/public/project_cmtlwofwa17hz01u26caa9ev9/subgraphs/glazecorp-zero-rpc/0.3.0/gn"
EXPLORE_URL = "https://www.glazecorp.io/explore"
WSM_AUCTIONS_URL = "https://www.glazecorp.io/coins/0x4aef7f76e2ce208f68e6646c385feb8843aa34a0/auctions"


def parse_bigint(val):
    if val is None:
        return 0
    if isinstance(val, (int, float)):
        return int(val)
    if isinstance(val, str) and val.startswith("$n"):
        return int(val[2:])
    try:
        return int(val)
    except Exception:
        return 0


def fetch_explore():
    explore_map = {}
    try:
        req_exp = urllib.request.Request(EXPLORE_URL, headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req_exp, timeout=10).read().decode("utf-8", errors="ignore")
        matches = re.findall(r'\{\\"coin\\":\\"0x[0-9a-fA-F]{40}\\",.*?\}(?=,{\\"coin\\"|\]\})', html)
        for m in matches:
            try:
                d = json.loads(m.encode("utf-8").decode("unicode_escape"))
                if d.get("symbol"):
                    explore_map[d["coin"].lower()] = d
            except Exception:
                pass
    except Exception:
        pass
    return explore_map


def fetch_subgraph():
    query = {
        "query": """
        {
          fundInstances(first: 200, orderBy: liquidityUsdgRaw, orderDirection: desc) {
            id
            launchId
            name
            symbol
            coin
            mine
            creatorFeeBps
            swapFee
            initialTpsRaw
            halvingPeriod
            tailTpsRaw
            totalSupplyRaw
            priceUsdg
            priceUsdgWad
            liquidityUsdgRaw
            volumeQuoteRaw
            swapCount
            holderCount
            miningPaymentsRaw
            pool {
              quoteIsUsdg
              reserveBaseRaw
              reserveQuoteRaw
              priceUsdgWad
              swapCount
              volumeQuoteRaw
            }
            miningSlots {
              epoch
              initialPriceRaw
              auctionStartedAt
              tpsRaw
              lastPriceRaw
              currentMessage
              currentMiner {
                id
              }
            }
          }
        }
        """
    }
    req_sg = urllib.request.Request(
        SUBGRAPH_URL,
        data=json.dumps(query).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    )
    resp = json.loads(urllib.request.urlopen(req_sg, timeout=10).read().decode("utf-8"))
    return resp.get("data", {}).get("fundInstances", [])


def fetch_wsm_strategy_auctions():
    try:
        req = urllib.request.Request(WSM_AUCTIONS_URL, headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", errors="ignore")
        pushes = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html)
        full_text = "".join(pushes).encode("utf-8").decode("unicode_escape", errors="ignore")

        prices = {}
        for m in re.finditer(r'"(0x[0-9a-fA-F]{40})":\{"status":"available".*?"priceUsd":"([0-9.]+)"', full_text):
            prices[m.group(1).lower()] = float(m.group(2))

        m_lp = re.search(r'"lpPriceUsdgWad":"\$n(\d+)"', full_text)
        lp_price = int(m_lp.group(1)) / 1e6 if m_lp else 81686.67
        m_wsm = re.search(r'"priceUsdgE36":"\$n(\d+)"', full_text)
        wsm_price = int(m_wsm.group(1)) / 1e24 if m_wsm else 0.001668

        prices["0xce5219cb417cddf4388ced8699a7cb8923ec914b"] = lp_price
        prices["0x4aef7f76e2ce208f68e6646c385feb8843aa34a0"] = wsm_price

        m_rate = re.search(r'"revenueRateRaw":"\$n(\d+)"', full_text)
        rev_rate_usdg_per_sec = int(m_rate.group(1)) / 1e6 if m_rate else 0.022209
        m_rem = re.search(r'"remainingRevenueRaw":"\$n(\d+)"', full_text)
        rem_usdg = int(m_rem.group(1)) / 1e6 if m_rem else 13241.0
        m_fin = re.search(r'"revenuePeriodFinish":"\$n(\d+)"', full_text)
        period_finish = int(m_fin.group(1)) if m_fin else 1794422827
        m_tot_sig = re.search(r'"totalSignalWeightRaw":"\$n(\d+)"', full_text)
        tot_signal = int(m_tot_sig.group(1)) / 1e18 if m_tot_sig else 2567.3

        idx_q4 = full_text.rfind('[{"address":"0x07ce0B01318135464CFcAeb109770eBC056098Ff"')
        if idx_q4 == -1:
            return None

        strats, _ = json.JSONDecoder().raw_decode(full_text[idx_q4:])
        now_ts = int(time.time())
        auctions_out = []

        for s in strats:
            pt = s.get("paymentToken") or {}
            raw_sym = pt.get("symbol") or "???"
            display_sym = "LP (WSM/USDG)" if "FullRange-WSM-USDG" in raw_sym else raw_sym
            dec = int(pt.get("decimals") or 18)
            pt_addr = (pt.get("address") or "").lower()
            p_usd = prices.get(pt_addr, 0.0)

            init_amt = parse_bigint(s.get("initialPriceRaw")) / (10**dec)
            curr_amt = parse_bigint(s.get("currentPriceRaw")) / (10**dec)
            started_at = parse_bigint(s.get("epochStartedAt"))
            dur_sec = parse_bigint(s.get("epochDuration")) or 86400
            held_usdg = parse_bigint(s.get("heldRevenueRaw")) / 1e6
            sig = parse_bigint(s.get("totalSignalRaw")) / 1e18

            share = (sig / tot_signal) if tot_signal > 0 else 0.0
            grow_hr = rev_rate_usdg_per_sec * 3600.0 * share
            drop_amt_hr = init_amt / (dur_sec / 3600.0)
            drop_usd_hr = drop_amt_hr * p_usd

            auctions_out.append({
                "strategy": s.get("address"),
                "symbol": display_sym,
                "raw_symbol": raw_sym,
                "token_name": pt.get("name") or display_sym,
                "token_address": pt.get("address"),
                "p_usd": p_usd,
                "init_amt": init_amt,
                "curr_amt": curr_amt,
                "started_at": started_at,
                "duration_sec": dur_sec,
                "pot_usdg": held_usdg,
                "snapshot_ts": now_ts,
                "signal_share": share,
                "grow_usd_hr": grow_hr,
                "drop_amt_hr": drop_amt_hr,
                "drop_usd_hr": drop_usd_hr
            })

        return {
            "fund_symbol": "WSM",
            "fund_coin": "0x4aef7f76e2ce208f68e6646c385feb8843aa34a0",
            "daily_usdg_rate": rev_rate_usdg_per_sec * 86400.0,
            "hourly_usdg_rate": rev_rate_usdg_per_sec * 3600.0,
            "remaining_usdg": rem_usdg,
            "period_finish": period_finish,
            "strategies": auctions_out
        }
    except Exception:
        return None


def get_full_live_payload():
    with ThreadPoolExecutor(max_workers=3) as ex:
        fut_exp = ex.submit(fetch_explore)
        fut_sg = ex.submit(fetch_subgraph)
        fut_wsm = ex.submit(fetch_wsm_strategy_auctions)

        explore_map = fut_exp.result()
        funds = fut_sg.result()
        wsm_auctions = fut_wsm.result()

    merged = []
    for f in funds:
        coin_addr = (f.get("coin") or f.get("id") or "").lower()
        exp = explore_map.get(coin_addr, {})
        pool = f.get("pool") or {}
        slot = (f.get("miningSlots") or [{}])[0]

        quote_is_usdg = bool(pool.get("quoteIsUsdg", True))
        r_base = int(pool.get("reserveBaseRaw") or 0) / 1e18
        r_quote = int(pool.get("reserveQuoteRaw") or 0) / 1e6

        exp_liq = parse_bigint(exp.get("liquidityUsdgRaw")) / 1e6
        sg_liq = int(f.get("liquidityUsdgRaw") or 0) / 1e6
        liq_usdg = exp_liq if exp_liq > 0 else (r_quote * 2.0 if quote_is_usdg else sg_liq)
        r_usdg = liq_usdg / 2.0

        exp_price = parse_bigint(exp.get("priceUsdgE36")) / 1e24
        if quote_is_usdg and r_base > 0 and r_quote > 0:
            p_token = r_quote / r_base
        elif exp_price > 0:
            p_token = exp_price
        else:
            p_token = int(f.get("priceUsdgWad") or 0) / 1e18

        vol24 = parse_bigint(exp.get("volume24hUsdgRaw")) / 1e6
        treasury = parse_bigint(exp.get("treasuryValueUsdgRaw")) / 1e6
        eff_supply = parse_bigint(exp.get("effectiveSupplyRaw")) / 1e18
        if eff_supply <= 0:
            eff_supply = int(f.get("totalSupplyRaw") or 0) / 1e18

        swaps24 = exp.get("swaps24h") or int(f.get("swapCount") or 0)
        takeovers24 = exp.get("takeovers24h") or int(slot.get("epoch") or 0)

        init_price_usdg = int(slot.get("initialPriceRaw") or 0) / 1e6
        auction_started_at = int(slot.get("auctionStartedAt") or 0)
        tps = int(slot.get("tpsRaw") or f.get("initialTpsRaw") or 0) / 1e18
        if tps <= 0:
            tps = 64.0
        last_paid_usdg = int(slot.get("lastPriceRaw") or 0) / 1e6
        cm = slot.get("currentMiner")
        miner_addr = cm.get("id") if isinstance(cm, dict) else (str(cm) if cm else "0x0000...0000")
        miner_msg = slot.get("currentMessage") or ""
        epoch = int(slot.get("epoch") or 0)
        swap_fee = int(f.get("swapFee") or 10000) / 1e6
        if swap_fee <= 0 or swap_fee > 0.2:
            swap_fee = 0.01

        merged.append({
            "coin": f.get("coin") or f.get("id"),
            "name": f.get("name") or exp.get("name") or "Unknown",
            "symbol": f.get("symbol") or exp.get("symbol") or "???",
            "p_token": p_token,
            "liq_usdg": liq_usdg,
            "r_usdg": r_usdg,
            "treasury_usdg": treasury,
            "eff_supply": eff_supply,
            "vol24_usdg": vol24,
            "swaps24": swaps24,
            "takeovers24": takeovers24,
            "init_price_usdg": init_price_usdg,
            "auction_started_at": auction_started_at,
            "tps": tps,
            "last_paid_usdg": last_paid_usdg,
            "miner": miner_addr,
            "message": miner_msg,
            "epoch": epoch,
            "swap_fee": swap_fee
        })

    merged.sort(key=lambda x: (x["liq_usdg"], x["vol24_usdg"]), reverse=True)
    return {
        "timestamp": int(time.time()),
        "tokens": merged,
        "strategy_auctions": wsm_auctions
    }


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        try:
            data = get_full_live_payload()
            payload = json.dumps(data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.end_headers()
            self.wfile.write(payload)
        except Exception as e:
            err_payload = json.dumps({"error": str(e), "tokens": []}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(err_payload)
