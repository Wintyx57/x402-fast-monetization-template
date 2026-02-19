"""x402 Fast Monetization Template -- Golden Script
Monetize any Python function with USDC payments on Base via HTTP 402.
"""

# ===========================================================================
# SECTION 1: Imports & Configuration
# ===========================================================================
import os, io, random, inspect, asyncio, logging, threading, time
from collections import Counter

import httpx, uvicorn, qrcode
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, PlainTextResponse

load_dotenv()

USDC_CONTRACT = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
USDC_DECIMALS = 6

WALLET_ADDRESS = os.getenv("WALLET_ADDRESS")
if not WALLET_ADDRESS:
    raise RuntimeError("WALLET_ADDRESS is required. Set it in your .env file.")
WALLET_ADDRESS = WALLET_ADDRESS.lower()

BASE_RPC_URL = os.getenv("BASE_RPC_URL", "https://mainnet.base.org")
BAZAAR_REGISTRY_URL = os.getenv("BAZAAR_REGISTRY_URL", "")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
PORT = int(os.getenv("PORT", "8000"))

app = FastAPI(title="x402 API", description="Pay-per-call API powered by x402 protocol")
logger = logging.getLogger("x402")

# ===========================================================================
# SECTION 2: Payment Verification Engine
# ===========================================================================
used_tx_hashes: set[str] = set()
_tx_lock = threading.Lock()

# Maximum age for accepted transactions (seconds)
MAX_TX_AGE_SECONDS = 300  # 5 minutes


async def verify_payment(tx_hash: str, expected_amount: float, expected_sender: str | None = None) -> dict:
    """Verify a USDC payment on Base via eth_getTransactionReceipt.

    S8 fix: Reserve the tx hash BEFORE blockchain verification to prevent race conditions.
    S7 fix: Verify the sender address matches the expected payer.
    """
    tx_hash = tx_hash.strip().lower()

    # S8 — Atomic check-and-reserve to prevent double-spend race condition
    with _tx_lock:
        if tx_hash in used_tx_hashes:
            return {"valid": False, "error": "Transaction already used"}
        used_tx_hashes.add(tx_hash)  # Reserve immediately

    try:
        rpc_payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "eth_getTransactionReceipt", "params": [tx_hash],
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(BASE_RPC_URL, json=rpc_payload)
        receipt = resp.json().get("result")

        if not receipt:
            with _tx_lock:
                used_tx_hashes.discard(tx_hash)
            return {"valid": False, "error": "Transaction not found or invalid"}
        if receipt.get("status") != "0x1":
            with _tx_lock:
                used_tx_hashes.discard(tx_hash)
            return {"valid": False, "error": "Transaction reverted"}

        # S7 — Verify transaction is recent (block timestamp < 5 minutes ago)
        block_hex = receipt.get("blockNumber")
        if block_hex:
            block_payload = {
                "jsonrpc": "2.0", "id": 2,
                "method": "eth_getBlockByNumber", "params": [block_hex, False],
            }
            async with httpx.AsyncClient(timeout=15) as client:
                block_resp = await client.post(BASE_RPC_URL, json=block_payload)
            block_result = block_resp.json().get("result")
            if block_result:
                block_ts = int(block_result.get("timestamp", "0x0"), 16)
                if time.time() - block_ts > MAX_TX_AGE_SECONDS:
                    with _tx_lock:
                        used_tx_hashes.discard(tx_hash)
                    return {"valid": False, "error": f"Transaction too old (>{MAX_TX_AGE_SECONDS}s). Only recent transactions accepted."}

        expected_raw = int(expected_amount * (10 ** USDC_DECIMALS))
        for log_entry in receipt.get("logs", []):
            if log_entry.get("address", "").lower() != USDC_CONTRACT.lower():
                continue
            topics = log_entry.get("topics", [])
            if len(topics) < 3 or topics[0].lower() != TRANSFER_TOPIC:
                continue
            to_addr = "0x" + topics[2][-40:]
            if to_addr.lower() != WALLET_ADDRESS:
                continue

            # S7 — Verify sender matches expected payer
            from_addr = "0x" + topics[1][-40:]
            if expected_sender and from_addr.lower() != expected_sender.strip().lower():
                with _tx_lock:
                    used_tx_hashes.discard(tx_hash)
                return {"valid": False, "error": f"Payment sender mismatch: expected {expected_sender}, got {from_addr}"}

            raw_amount = int(log_entry.get("data", "0x0"), 16)
            if raw_amount >= expected_raw:
                return {"valid": True, "error": None}
            got = raw_amount / (10 ** USDC_DECIMALS)
            with _tx_lock:
                used_tx_hashes.discard(tx_hash)
            return {"valid": False, "error": f"Insufficient payment: expected {expected_amount} USDC, got {got}"}

        with _tx_lock:
            used_tx_hashes.discard(tx_hash)
        return {"valid": False, "error": "No matching USDC transfer found in transaction"}
    except Exception as exc:
        # On any error, release the reserved hash
        with _tx_lock:
            used_tx_hashes.discard(tx_hash)
        raise exc

# ===========================================================================
# SECTION 3: Decorator @x402_paywall
# ===========================================================================
PAYWALL_REGISTRY: list[dict] = []


def x402_paywall(price: float, description: str = "", tags: list[str] | None = None):
    """Decorator: turns a Python function into a paid FastAPI GET endpoint."""
    tags_ = tags or []

    def decorator(func):
        path = f"/{func.__name__}"
        sig = inspect.signature(func)
        is_coro = asyncio.iscoroutinefunction(func)
        ret = sig.return_annotation
        returns_bytes, returns_str = (ret is bytes), (ret is str)

        PAYWALL_REGISTRY.append({
            "name": func.__name__, "path": path,
            "price": str(price), "description": description, "tags": tags_,
        })

        async def route_handler(request: Request, **kwargs):
            tx_hash = request.headers.get("X-Payment-TxHash")
            if not tx_hash:
                return JSONResponse(status_code=402, content={
                    "error": "Payment Required",
                    "payment_details": {
                        "amount": str(price), "currency": "USDC",
                        "network": "Base", "chain_id": 8453,
                        "recipient": WALLET_ADDRESS,
                        "usdc_contract": USDC_CONTRACT, "rpc_url": BASE_RPC_URL,
                        "instructions": "Send USDC on Base to the recipient address, then retry with headers X-Payment-TxHash: 0x... and X-Payer-Address: 0x...",
                    },
                })

            # S7 — Verify sender address if provided
            payer_address = request.headers.get("X-Payer-Address")
            check = await verify_payment(tx_hash, price, expected_sender=payer_address)
            if not check["valid"]:
                return JSONResponse(status_code=402, content={"error": check["error"]})

            output = (await func(**kwargs)) if is_coro else func(**kwargs)
            payment_meta = {"tx_hash": tx_hash.strip().lower(), "amount_charged": str(price), "currency": "USDC"}

            if returns_bytes:
                return Response(content=output, media_type="image/png")
            if returns_str:
                return PlainTextResponse(content=output)
            return JSONResponse(content={"result": output, "payment": payment_meta})

        # Mirror the original function's parameters as query params
        params = [inspect.Parameter("request", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Request)]
        for name, p in sig.parameters.items():
            default = p.default if p.default is not inspect.Parameter.empty else ...
            ann = p.annotation if p.annotation is not inspect.Parameter.empty else str
            params.append(inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, default=default, annotation=ann))
        route_handler.__signature__ = inspect.Signature(params)
        route_handler.__name__ = func.__name__
        route_handler.__doc__ = description or func.__doc__

        app.get(path, summary=description, tags=tags_ or ["paid"])(route_handler)
        return func

    return decorator

# ===========================================================================
# SECTION 4: Marketplace Registration
# ===========================================================================
@app.on_event("startup")
async def register_on_marketplace():
    """Auto-register all paid endpoints on x402 Bazaar at startup."""
    if not BAZAAR_REGISTRY_URL:
        logger.warning("Marketplace registration skipped: BAZAAR_REGISTRY_URL not set")
        return
    async with httpx.AsyncClient(timeout=10) as client:
        for entry in PAYWALL_REGISTRY:
            payload = {
                "name": entry["name"],
                "url": f"{API_BASE_URL.rstrip('/')}{entry['path']}",
                "price": entry["price"], "currency": "USDC", "network": "Base",
                "description": entry["description"], "tags": entry["tags"],
                "protocol": "x402",
            }
            try:
                resp = await client.post(f"{BAZAAR_REGISTRY_URL.rstrip('/')}/api/register", json=payload)
                logger.info("Registered %s on marketplace (status %d)", entry["name"], resp.status_code)
            except Exception as exc:
                logger.warning("Failed to register %s: %s", entry["name"], exc)

# ===========================================================================
# SECTION 5: Example Paid Functions
# ===========================================================================
@x402_paywall(price=0.05, description="Generate a QR code image from text", tags=["qr", "image", "generator"])
def generate_qr(text: str) -> bytes:
    """Generate a PNG QR code for the given text."""
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@x402_paywall(price=0.03, description="Summarize text using extractive method", tags=["text", "nlp", "summary"])
def summarize(text: str, max_sentences: int = 3) -> dict:
    """Extract the most important sentences using word frequency scoring."""
    sentences = [s.strip() for s in text.replace("!", ".").replace("?", ".").split(".") if s.strip()]
    if len(sentences) <= max_sentences:
        return {"summary": ". ".join(sentences) + ".", "sentence_count": len(sentences)}
    words = text.lower().split()
    freq = Counter(words)
    scores = {i: sum(freq[w.lower()] for w in s.split()) for i, s in enumerate(sentences)}
    top = sorted(sorted(scores, key=scores.get, reverse=True)[:max_sentences])
    return {"summary": ". ".join(sentences[i] for i in top) + ".", "sentence_count": len(top)}


JOKES = [
    "Why do programmers prefer dark mode? Because light attracts bugs.",
    "There are only 10 types of people: those who understand binary and those who don't.",
    "A SQL query walks into a bar, sees two tables and asks: 'Can I JOIN you?'",
    "Why do Java developers wear glasses? Because they can't C#.",
    "How many programmers does it take to change a light bulb? None, that's a hardware problem.",
    "!false -- it's funny because it's true.",
    "A programmer's wife tells him: 'Go buy bread. If they have eggs, buy a dozen.' He comes home with 12 loaves.",
    "Why did the developer go broke? Because he used up all his cache.",
    "What's a programmer's favorite hangout? Foo Bar.",
    "To understand recursion, you must first understand recursion.",
    "There's no place like 127.0.0.1.",
    "Algorithm: a word used by programmers when they don't want to explain what they did.",
]


@x402_paywall(price=0.01, description="Get a random programming joke", tags=["fun", "joke", "text"])
def random_joke() -> dict:
    """Return a random programming joke."""
    return {"joke": random.choice(JOKES)}

# ===========================================================================
# SECTION 6: Health Check & Entry Point
# ===========================================================================
@app.get("/", tags=["info"])
def index():
    """List all available paid endpoints."""
    endpoints = [
        {"path": e["path"], "price_usdc": e["price"], "description": e["description"], "tags": e["tags"]}
        for e in PAYWALL_REGISTRY
    ]
    return {"service": "x402 API", "endpoints": endpoints, "docs": "/docs"}


@app.get("/health", tags=["info"])
def health():
    """Health check endpoint."""
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
