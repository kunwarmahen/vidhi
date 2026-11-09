#!/usr/bin/env bash
# The marketplace on the internet, without a domain or an open router port:
# Tailscale Funnel. Tailscale gives this computer a name
# (https://<computer>.<your-tailnet>.ts.net), holds its certificate, and
# forwards that name's HTTPS to the marketplace alone on 127.0.0.1 -- only
# /market/: no routines of yours, no runs, no API.
# Run it yourself: it signs in to your Tailscale account and asks for your
# password (sudo).
#
#   deploy/public-market-tailscale.sh [PORT]
#
# PORT is the marketplace's (vidhi market serve --port 8787, or
# [vidhi] market_port in sarathi.toml). Funnel serves three public ports:
# 443 (a Setu catalog), 8443 (Prahari's inlet), so the marketplace takes
# 10000. Undo with:
#   sudo tailscale funnel --https=10000 off
set -euo pipefail
PORT="${1:-8787}"

said=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/market/index" || true)
if [ "$said" != "200" ]; then
    echo "The marketplace isn't answering on 127.0.0.1:$PORT (got '$said', want 200)."
    echo "Start it alone on that port: vidhi market serve --dir ~/.vidhi-market --port $PORT"
    echo "(with Sarathi: market_port = $PORT under [vidhi], then sarathi up)"
    exit 1
fi

if ! command -v tailscale >/dev/null; then
    echo "Installing Tailscale with its own installer (tailscale.com/install.sh)..."
    curl -fsSL https://tailscale.com/install.sh | sh
fi

# Signs this computer in to your tailnet; prints a link to open the first time.
sudo tailscale up

# If Funnel isn't allowed for this computer yet, tailscale prints a link to
# allow it in your tailnet's settings: open it, allow, and run this again.
sudo tailscale funnel --bg --https=10000 "http://127.0.0.1:$PORT"

NAME=$(tailscale status --json | python3 -c \
    'import json, sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')
PUBLIC="https://$NAME:10000"
echo
echo "The marketplace's public address: $PUBLIC/market/"
echo -n "Its list answers: "
curl -s -o /dev/null -w '%{http_code}\n' "$PUBLIC/market/index" || true
echo "(200 is right)"
echo
echo "Next, tell Vidhi (and the people who'll use it) this address:"
echo "  export VIDHI_MARKET=$PUBLIC   (each person: their Vidhi's marketplace)"
echo "  (with Sarathi: market_url = \"$PUBLIC\" under [vidhi], then sarathi up)"
echo "And publish your reviewers' public keys somewhere people already trust"
echo "(your GitHub profile, say), so they can compare before: vidhi market trust"
