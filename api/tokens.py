from http.server import BaseHTTPRequestHandler
import urllib.request
import json
import re
import time

SUBGRAPH_URL = "https://api.goldsky.com/api/public/project_cmtlwofwa17hz01u26caa9ev9/subgraphs/glazecorp-zero-rpc/0.3.0/gn"
EXPLORE_URL = "https://www.glazecorp.io/explore"


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


def get_merged_tokens():
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
    funds = resp.get("data", {}).get("fundInstances", [])

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
    return merged


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        try:
            tokens = get_merged_tokens()
            payload = json.dumps({"timestamp": int(time.time()), "tokens": tokens}).encode("utf-8")
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
