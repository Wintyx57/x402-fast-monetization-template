# x402 Fast Monetization Template

**Monetize any Python function in 3 steps.** Turn your code into a paid API with USDC payments on Base -- no backend experience needed.

![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![License MIT](https://img.shields.io/badge/License-MIT-green)
![USDC on Base](https://img.shields.io/badge/USDC-Base-3C5CFF?logo=ethereum&logoColor=white)
![x402 Protocol](https://img.shields.io/badge/Protocol-x402-orange)

---

## Table of Contents

- [Quick Start (3 Steps)](#quick-start-3-steps)
- [One-Click Replit Deploy](#one-click-replit-deploy)
- [How the @x402_paywall Decorator Works](#how-the-x402_paywall-decorator-works)
- [Add Your Own Function](#add-your-own-function)
- [Included Examples](#included-examples)
- [The x402 Protocol](#the-x402-protocol)
- [Environment Variables](#environment-variables)
- [API Documentation](#api-documentation)
- [Project Structure](#project-structure)
- [Links](#links)
- [License](#license)

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

Open `.env` and replace the placeholder with your Ethereum wallet address:

```env
WALLET_ADDRESS=0xYOUR_ACTUAL_WALLET_ADDRESS
```

This is the address that will receive USDC payments from API callers.

### 3. Run

```bash
python main.py
```

Your API is live at **http://localhost:8000/docs** -- open it to see the interactive Swagger UI.

---

## One-Click Replit Deploy

[![Run on Replit](https://replit.com/badge/github/Wintyx57/x402-fast-monetization-template)](https://replit.com/@Wintyx57/x402-fast-monetization-template)

1. Click the button above
2. Set `WALLET_ADDRESS` in the Replit Secrets tab
3. Hit **Run** -- your paid API is live with a public URL

---

## How the @x402_paywall Decorator Works

The `@x402_paywall` decorator transforms any Python function into a paid FastAPI endpoint. One decorator, one line:

```python
from main import x402_paywall

@x402_paywall(price=0.05, description="My cool API", tags=["cool"])
def my_function(param: str) -> dict:
    return {"result": f"You sent: {param}"}
```

What happens under the hood:

- The function name becomes the endpoint path (`/my_function`)
- Function parameters become query parameters (`?param=hello`)
- The return type hint controls the response format:
  - `dict` -- JSON response
  - `bytes` -- Binary response (e.g., PNG image)
  - `str` -- Plain text response
- Callers without a valid payment get a `402 Payment Required` response with instructions
- Callers with a valid `X-Payment-TxHash` header get the function result

---

## Add Your Own Function

Adding a new paid endpoint takes 3 steps. Open `main.py` and scroll to **Section 5**.

### Step 1: Write your function

```python
def my_api(query: str, limit: int = 10) -> dict:
    """Your logic here."""
    results = do_something(query, limit)
    return {"data": results}
```

### Step 2: Add the decorator

```python
@x402_paywall(price=0.02, description="Search my database", tags=["search", "data"])
def my_api(query: str, limit: int = 10) -> dict:
    """Your logic here."""
    results = do_something(query, limit)
    return {"data": results}
```

### Step 3: Restart the server

```bash
python main.py
```

Your new endpoint is live at `GET /my_api?query=hello&limit=5` and visible in `/docs`.

**Decorator parameters:**

| Parameter     | Type       | Required | Description                          |
|---------------|------------|----------|--------------------------------------|
| `price`       | `float`    | Yes      | Price in USDC per call               |
| `description` | `str`      | No       | Shown in Swagger UI and marketplace  |
| `tags`        | `list[str]`| No       | Used for categorization              |

---

## Included Examples

The template ships with 3 working examples you can try immediately:

| Endpoint        | Price (USDC) | Description                          | Parameters                   | Returns  |
|-----------------|-------------|--------------------------------------|------------------------------|----------|
| `/generate_qr`  | 0.05        | Generate a QR code image from text   | `text` (str)                 | PNG image|
| `/summarize`    | 0.03        | Summarize text using extractive method | `text` (str), `max_sentences` (int, default 3) | JSON |
| `/random_joke`  | 0.01        | Get a random programming joke        | None                         | JSON     |

No external API keys needed -- all examples run with zero configuration beyond `WALLET_ADDRESS`.

---

## The x402 Protocol

x402 uses the HTTP 402 status code ("Payment Required") to create a machine-readable payment flow:

```
Client                          Your API                         Base (L2)
  |                                |                                |
  |  1. GET /generate_qr?text=hi  |                                |
  |------------------------------->|                                |
  |                                |                                |
  |  2. 402 + payment_details      |                                |
  |<-------------------------------|                                |
  |                                |                                |
  |  3. Send USDC to recipient     |                                |
  |--------------------------------------------------------------->|
  |                                |                                |
  |  4. GET /generate_qr?text=hi   |                                |
  |    + X-Payment-TxHash: 0xabc   |                                |
  |------------------------------->|                                |
  |                                |  5. Verify tx on-chain         |
  |                                |------------------------------->|
  |                                |                                |
  |  6. 200 + QR code image        |                                |
  |<-------------------------------|                                |
```

**Step by step:**

1. **Client calls your API** without payment
2. **Server responds 402** with payment details (amount, recipient wallet, USDC contract address, network)
3. **Client sends USDC** on Base to your wallet address
4. **Client retries** the same request with the transaction hash in the `X-Payment-TxHash` header
5. **Server verifies** the transaction on-chain (correct recipient, sufficient amount, not replayed)
6. **Access granted** -- the function executes and returns the result

The 402 response body looks like this:

```json
{
  "error": "Payment Required",
  "payment_details": {
    "amount": "0.05",
    "currency": "USDC",
    "network": "Base",
    "chain_id": 8453,
    "recipient": "0xYOUR_WALLET_ADDRESS",
    "usdc_contract": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "rpc_url": "https://mainnet.base.org",
    "instructions": "Send USDC on Base to the recipient address, then retry with header X-Payment-TxHash: 0x..."
  }
}
```

---

## Environment Variables

Configure your API via a `.env` file (copy `.env.example` to get started):

| Variable              | Required | Default                        | Description                                       |
|-----------------------|----------|--------------------------------|---------------------------------------------------|
| `WALLET_ADDRESS`      | Yes      | --                             | Your Ethereum address to receive USDC payments    |
| `BASE_RPC_URL`        | No       | `https://mainnet.base.org`     | Base RPC endpoint for on-chain verification        |
| `BAZAAR_REGISTRY_URL` | No       | --                             | x402 Bazaar URL for auto-registering your endpoints|
| `API_BASE_URL`        | No       | `http://localhost:8000`        | Public URL of your API (used for marketplace)      |
| `PORT`                | No       | `8000`                         | Server listening port                              |

---

## API Documentation

FastAPI auto-generates interactive API docs. Once the server is running:

- **Swagger UI** -- [http://localhost:8000/docs](http://localhost:8000/docs)
- **Health check** -- `GET /` returns a list of all paid endpoints
- **Status** -- `GET /health` returns `{"status": "ok"}`

---

## Project Structure

```
x402-fast-monetization-template/
  main.py             # Single-file API -- all logic lives here
  requirements.txt    # Python dependencies
  .env.example        # Environment variable template
  .replit             # Replit run configuration
  replit.nix          # Replit system dependencies
  LICENSE             # MIT License
  README.md           # This file
  SPECS.md            # Full technical specifications
```

Everything runs from `main.py`. One file, no framework boilerplate, no build step.

---

## Links

- **x402 Bazaar Marketplace** -- [https://x402bazaar.org](https://x402bazaar.org)
- **CLI Quick Start** -- `npx x402-bazaar init`
- **Backend Repository** -- [https://github.com/Wintyx57/x402-backend](https://github.com/Wintyx57/x402-backend)
- **Frontend Repository** -- [https://github.com/Wintyx57/x402-frontend](https://github.com/Wintyx57/x402-frontend)

---

## License

[MIT](LICENSE) -- Use it, fork it, monetize with it.
