# x402 Fast Monetization Template

**Turn any Python function into a zero-gas AI Agent API — monetized with USDC, live in 3 steps.**

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![USDC](https://img.shields.io/badge/USDC-Base%20%7C%20SKALE-green)
![License](https://img.shields.io/badge/License-MIT-yellow)
![x402](https://img.shields.io/badge/Protocol-x402-purple)

---

## What is this?

This template lets you monetize any Python function as a pay-per-call API using USDC and the [x402 protocol](https://x402bazaar.org). One decorator is all it takes. No subscription logic, no API keys to manage for your callers, no billing infrastructure.

The killer feature: **SKALE on Base is the default chain**. SKALE on Base has ultra-low gas fees (~$0.0007/tx via CREDITS) — AI agents and bots can make hundreds of micro-payments per minute without burning money on gas. On Base you pay ~$0.001 per transaction; on SKALE on Base you pay a fraction of a cent.

---

## Quick Start (3 Steps)

### 1. Clone and install

```bash
git clone https://github.com/Wintyx57/x402-fast-monetization-template.git
cd x402-fast-monetization-template
pip install -r requirements.txt
```

### 2. Set your wallet

```bash
cp .env.example .env
```

Open `.env` and set your wallet address:

```env
WALLET_ADDRESS=0xYOUR_ACTUAL_WALLET_ADDRESS
```

### 3. Run

```bash
python main.py
```

Your API is live at **http://localhost:8000/docs** — open it to see the interactive Swagger UI.

---

## How It Works

The x402 protocol reuses the HTTP 402 status code ("Payment Required") to create a machine-readable payment flow that AI agents can navigate autonomously:

```
Client / AI Agent                 Your API                      Chain (SKALE or Base)
        |                              |                                  |
        |  1. GET /generate_qr         |                                  |
        |----------------------------->|                                  |
        |                              |                                  |
        |  2. 402 + payment_details    |                                  |
        |    (amount, wallet, network) |                                  |
        |<-----------------------------|                                  |
        |                              |                                  |
        |  3. Send USDC on SKALE       |                                  |
        |---------------------------------------------------------------->|
        |                              |                                  |
        |  4. GET /generate_qr         |                                  |
        |    + X-Payment-TxHash: 0x... |                                  |
        |    + X-Payment-Chain: skale  |                                  |
        |----------------------------->|                                  |
        |                              |  5. Verify tx on-chain           |
        |                              |--------------------------------->|
        |                              |                                  |
        |  6. 200 + result             |                                  |
        |<-----------------------------|                                  |
```

1. Client calls your API without payment
2. Server responds 402 with payment details (amount, recipient, USDC contract, all supported networks)
3. Client sends USDC on the chain of its choice
4. Client retries with `X-Payment-TxHash` and optionally `X-Payment-Chain` headers
5. Server verifies the on-chain transaction (correct recipient, sufficient amount, not replayed)
6. Access granted — your function executes and returns the result

---

## Supported Networks

| Chain | Gas Cost | USDC Contract | Chain ID |
|-------|----------|---------------|----------|
| Base | ~$0.001 | `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` | 8453 |
| **SKALE on Base** (default) | **~$0.0007** (CREDITS gas token) | `0x85889c8c714505E0c94b30fcfcF64fE3Ac8FCb20` | 1187947933 |

Both chains are listed in the 402 response under `payment_details.networks` so agents can pick the cheapest option automatically.

To change the default chain, set `DEFAULT_CHAIN=base` in your `.env`.

---

## The @x402_paywall Decorator

One decorator turns any Python function into a paid FastAPI endpoint:

```python
@x402_paywall(price=0.05, description="My paid API", tags=["cool"])
def my_function(param: str) -> dict:
    return {"result": f"You sent: {param}"}
```

What happens automatically:

- The function name becomes the endpoint path (`/my_function`)
- Function parameters become URL query parameters (`?param=hello`)
- The return type hint controls the response format:
  - `dict` -- JSON response
  - `bytes` -- Binary response (e.g., PNG image)
  - `str` -- Plain text response
- Callers without a valid payment get a `402` with full payment instructions
- Callers with a valid `X-Payment-TxHash` get the function result

The 402 response body that agents receive:

```json
{
  "error": "Payment Required",
  "payment_details": {
    "amount": "0.05",
    "currency": "USDC",
    "network": "SKALE on Base",
    "chain_id": 1187947933,
    "recipient": "0xYOUR_WALLET_ADDRESS",
    "usdc_contract": "0x85889c8c714505E0c94b30fcfcF64fE3Ac8FCb20",
    "networks": [
      { "chain": "base", "label": "Base", "chain_id": 8453, "gas": "~$0.001", ... },
      { "chain": "skale", "label": "SKALE on Base", "chain_id": 1187947933, "gas": "~$0.0007 (CREDITS)", ... }
    ],
    "instructions": "Send USDC on SKALE on Base to the recipient address, then retry with headers X-Payment-TxHash: 0x... and X-Payer-Address: 0x... Optionally add X-Payment-Chain: base|skale to select the network."
  }
}
```

---

## Add Your Own API

Open `main.py` and go to **Section 5**. Adding a new paid endpoint is 3 lines:

```python
@x402_paywall(price=0.02, description="Search my database", tags=["search", "data"])
def my_api(query: str, limit: int = 10) -> dict:
    results = do_something(query, limit)
    return {"data": results}
```

Restart the server — your endpoint is live at `GET /my_api?query=hello&limit=5` and visible in `/docs`.

**Decorator parameters:**

| Parameter     | Type        | Required | Description                         |
|---------------|-------------|----------|-------------------------------------|
| `price`       | `float`     | Yes      | Price in USDC per call              |
| `description` | `str`       | No       | Shown in Swagger UI and marketplace |
| `tags`        | `list[str]` | No       | Used for categorization             |

---

## Included Examples

The template ships with 3 working endpoints, no external API keys required:

| Endpoint        | Price (USDC) | Description                              | Returns   |
|-----------------|-------------|------------------------------------------|-----------|
| `/generate_qr`  | 0.05        | Generate a QR code image from text       | PNG image |
| `/summarize`    | 0.03        | Summarize text (extractive, word-freq)   | JSON      |
| `/random_joke`  | 0.01        | Get a random programming joke            | JSON      |

---

## Environment Variables

| Variable              | Required | Default        | Description                                           |
|-----------------------|----------|----------------|-------------------------------------------------------|
| `WALLET_ADDRESS`      | Yes      | --             | Your Ethereum address to receive USDC payments        |
| `DEFAULT_CHAIN`       | No       | `skale`        | Default payment chain: `skale` or `base`              |
| `BASE_RPC_URL`        | No       | chain default  | Override the Base RPC endpoint                        |
| `BAZAAR_REGISTRY_URL` | No       | --             | x402 Bazaar URL for auto-registering your endpoints   |
| `API_BASE_URL`        | No       | `http://localhost:8000` | Public URL of your API (used for marketplace) |
| `PORT`                | No       | `8000`         | Server listening port                                 |

---

## Deploy

**Replit (one-click):**

[![Run on Replit](https://replit.com/badge/github/Wintyx57/x402-fast-monetization-template)](https://replit.com/@Wintyx57/x402-fast-monetization-template)

1. Click the button above
2. Set `WALLET_ADDRESS` in the Replit Secrets tab
3. Hit Run — your API is live with a public URL

**Railway / Render:**

```bash
# Set environment variables in the dashboard, then deploy:
git push
```

Both platforms detect Python automatically. Set `WALLET_ADDRESS` and optionally `DEFAULT_CHAIN` in the environment variables panel.

---

## Links

| Resource | URL |
|----------|-----|
| x402 Bazaar marketplace | [x402bazaar.org](https://x402bazaar.org) |
| Backend API | [x402-api.onrender.com](https://x402-api.onrender.com) |
| CLI (`npx x402-bazaar`) | [x402-bazaar-cli](https://github.com/Wintyx57/x402-bazaar-cli) |
| TypeScript SDK | [x402-sdk](https://github.com/Wintyx57/x402-sdk) |
| LangChain tools | [x402-langchain](https://github.com/Wintyx57/x402-langchain) |
| MCP Server | [x402-backend](https://github.com/Wintyx57/x402-backend) |

---

## License

[MIT](LICENSE) — Use it, fork it, monetize with it.
