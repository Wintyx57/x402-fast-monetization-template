"""x402 Fast Monetization Template -- Golden Script
Monetize any Python function with USDC payments on Base or SKALE Europa via HTTP 402.
"""

# ===========================================================================
# SECTION 1: Imports & Configuration
# ===========================================================================
import os, io, random, inspect, asyncio, logging, threading, time, json, hmac, hashlib, fcntl
from collections import Counter
from pathlib import Path

import httpx, uvicorn, qrcode
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, PlainTextResponse

load_dotenv()

CHAINS = {
    "base": {
        "rpc_url": "https://mainnet.base.org",
        "usdc_contract": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "chain_id": 8453,
        "label": "Base",
        "explorer": "https://basescan.org",
        "gas": "~$0.001",
    },
    "skale": {
        "rpc_url": "https://mainnet.skalenodes.com/v1/elated-tan-skat",
        "usdc_contract": "0x5F795bb52dAc3085f578f4877D450e2929D2F13d",
        "chain_id": 2046399126,
        "label": "SKALE Europa",
        "explorer": "https://elated-tan-skat.explorer.mainnet.skalenodes.com",
        "gas": "FREE (zero gas with sFUEL)",
    },
}
DEFAULT_CHAIN = os.getenv("DEFAULT_CHAIN", "skale")  # Default to SKALE for zero gas!

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
USDC_DECIMALS = 6

# ===========================================================================
# SECTION 1A: Input Validation Functions
# ===========================================================================
def validate_ethereum_address(addr: str) -> str:
    """Validate and normalize an Ethereum address (0x + 40 hex chars)."""
    if not addr:
        raise ValueError("Address cannot be empty")
    addr = addr.strip()
    if not addr.startswith("0x"):
        raise ValueError(f"Address must start with '0x', got: {addr}")
    if len(addr) != 42:
        raise ValueError(f"Address must be exactly 42 chars (0x + 40 hex), got {len(addr)} chars")
    try:
        int(addr[2:], 16)
    except ValueError:
        raise ValueError(f"Address contains invalid hex characters: {addr}")
    return addr.lower()


def validate_rpc_url(url: str) -> str:
    """Validate RPC URL format (must be https:// or http://localhost)."""
    if not url:
        raise ValueError("RPC URL cannot be empty")
    url = url.strip()
    if url.startswith("https://"):
        return url
    if url.startswith("http://localhost"):
        return url
    raise ValueError(
        f"RPC URL must use https:// or http://localhost. Got: {url}\n"
        "For security, only HTTPS RPC endpoints or localhost are allowed."
    )


WALLET_ADDRESS = os.getenv("WALLET_ADDRESS")
if not WALLET_ADDRESS:
    raise RuntimeError("WALLET_ADDRESS is required. Set it in your .env file.")
try:
    WALLET_ADDRESS = validate_ethereum_address(WALLET_ADDRESS)
except ValueError as e:
    raise RuntimeError(f"Invalid WALLET_ADDRESS: {e}")

# BASE_RPC_URL is optional: if set, it overrides the RPC for the default chain.
_base_rpc_override = os.getenv("BASE_RPC_URL")
if _base_rpc_override:
    try:
        _base_rpc_override = validate_rpc_url(_base_rpc_override)
    except ValueError as e:
        raise RuntimeError(f"Invalid BASE_RPC_URL: {e}")
    CHAINS["base"]["rpc_url"] = _base_rpc_override

# Validate DEFAULT_CHAIN value
if DEFAULT_CHAIN not in CHAINS:
    raise RuntimeError(f"DEFAULT_CHAIN must be one of {list(CHAINS.keys())}, got: {DEFAULT_CHAIN}")

BAZAAR_REGISTRY_URL = os.getenv("BAZAAR_REGISTRY_URL", "")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
PORT = int(os.getenv("PORT", "8000"))

app = FastAPI(title="x402 API", description="Pay-per-call API powered by x402 protocol")
logger = logging.getLogger("x402")

# ===========================================================================
# SECTION 2: Persistent Transaction Store
# ===========================================================================
# File-based storage for used transaction hashes to prevent replay attacks
# across server restarts and multiple uvicorn workers.

TX_STORE_PATH = Path(os.getenv("TX_STORE_PATH", "tx_store.json"))
TX_STORE_LOCK_PATH = TX_STORE_PATH.with_suffix(".lock")
MAX_TX_AGE_SECONDS = int(os.getenv("TX_MAX_AGE_SECONDS", "300"))  # 5 minutes default

if MAX_TX_AGE_SECONDS < 60:
    logger.warning("TX_MAX_AGE_SECONDS is very small (%d seconds), consider increasing for robustness", MAX_TX_AGE_SECONDS)


def _acquire_lock():
    """Acquire file lock for safe concurrent access to tx_store.json."""
    lock_file = open(TX_STORE_LOCK_PATH, "a")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        return lock_file
    except Exception:
        lock_file.close()
        raise


def _release_lock(lock_file):
    """Release file lock."""
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    finally:
        lock_file.close()


def _load_tx_store() -> dict:
    """Load used transaction hashes from persistent storage.

    Returns dict with format: {"hashes": [{"hash": "0x...", "timestamp": 123456}]}
    """
    if not TX_STORE_PATH.exists():
        return {"hashes": []}
    try:
        with open(TX_STORE_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        logger.warning("Failed to load tx_store, starting fresh")
        return {"hashes": []}


def _save_tx_store(data: dict):
    """Persist transaction hashes to file with atomic write."""
    try:
        # Write to temp file first, then rename for atomicity
        temp_path = TX_STORE_PATH.with_suffix(".tmp")
        with open(temp_path, "w") as f:
            json.dump(data, f)
        temp_path.replace(TX_STORE_PATH)
    except IOError as e:
        logger.error("Failed to save tx_store: %s", e)


def _cleanup_expired_hashes(data: dict) -> dict:
    """Remove transaction hashes older than MAX_TX_AGE_SECONDS."""
    current_time = time.time()
    original_count = len(data["hashes"])
    data["hashes"] = [
        entry for entry in data["hashes"]
        if current_time - entry["timestamp"] <= MAX_TX_AGE_SECONDS
    ]
    if len(data["hashes"]) < original_count:
        logger.debug("Cleaned up %d expired transaction hashes", original_count - len(data["hashes"]))
    return data


def is_tx_hash_used(tx_hash: str) -> bool:
    """Check if transaction hash has been used (timing-safe comparison)."""
    lock_file = _acquire_lock()
    try:
        data = _load_tx_store()
        data = _cleanup_expired_hashes(data)

        for entry in data["hashes"]:
            # Use timing-safe comparison to prevent timing attacks
            if hmac.compare_digest(entry["hash"], tx_hash.lower()):
                return True
        return False
    finally:
        _release_lock(lock_file)


def mark_tx_hash_used(tx_hash: str) -> bool:
    """Mark a transaction hash as used. Returns False if already used."""
    lock_file = _acquire_lock()
    try:
        data = _load_tx_store()
        data = _cleanup_expired_hashes(data)

        tx_hash_lower = tx_hash.lower()

        # Check if already used (timing-safe)
        for entry in data["hashes"]:
            if hmac.compare_digest(entry["hash"], tx_hash_lower):
                return False  # Already used

        # Add new hash
        data["hashes"].append({
            "hash": tx_hash_lower,
            "timestamp": time.time()
        })
        _save_tx_store(data)
        return True
    finally:
        _release_lock(lock_file)


def remove_tx_hash_reservation(tx_hash: str):
    """Remove a transaction hash reservation (called on verification failure)."""
    lock_file = _acquire_lock()
    try:
        data = _load_tx_store()
        data = _cleanup_expired_hashes(data)

        tx_hash_lower = tx_hash.lower()
        original_count = len(data["hashes"])

        # Remove the hash
        data["hashes"] = [
            entry for entry in data["hashes"]
            if not hmac.compare_digest(entry["hash"], tx_hash_lower)
        ]

        if len(data["hashes"]) < original_count:
            _save_tx_store(data)
            logger.debug("Removed tx_hash reservation for failed verification")
    finally:
        _release_lock(lock_file)


# Load and cleanup existing hashes at startup
@app.on_event("startup")
async def _startup_handler():
    """Handle startup: clean up expired hashes and register marketplace."""
    # Clean up expired transaction hashes
    lock_file = _acquire_lock()
    try:
        data = _load_tx_store()
        original_count = len(data["hashes"])
        data = _cleanup_expired_hashes(data)
        if len(data["hashes"]) < original_count:
            _save_tx_store(data)
            logger.info(
                "Cleaned up %d expired hashes at startup (max_age=%ds)",
                original_count - len(data["hashes"]),
                MAX_TX_AGE_SECONDS
            )
    finally:
        _release_lock(lock_file)

    # Register on marketplace
    await _register_on_marketplace()


# ===========================================================================
# SECTION 2B: Payment Verification Engine
# ===========================================================================


async def verify_payment(tx_hash: str, expected_amount: float, expected_sender: str | None = None, chain: str | None = None) -> dict:
    """Verify a USDC payment on Base or SKALE Europa via eth_getTransactionReceipt.

    This function implements multiple security checks:
    - S8: Atomic check-and-reserve to prevent double-spend race conditions (file-based, persistent)
    - S7: Verify sender address matches expected payer
    - S6: Use timing-safe comparison to prevent timing attacks
    - S5: Validate transaction age
    """
    tx_hash = tx_hash.strip().lower()

    chain_key = chain if chain in CHAINS else DEFAULT_CHAIN
    chain_cfg = CHAINS[chain_key]
    rpc_url = chain_cfg["rpc_url"]
    usdc_contract = chain_cfg["usdc_contract"]

    # S8 — Atomic check-and-reserve using persistent file store to prevent
    # double-spend race conditions across server restarts and multiple workers
    if not mark_tx_hash_used(tx_hash):
        return {"valid": False, "error": "Transaction already used"}

    try:
        rpc_payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "eth_getTransactionReceipt", "params": [tx_hash],
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(rpc_url, json=rpc_payload)
        receipt = resp.json().get("result")

        if not receipt:
            remove_tx_hash_reservation(tx_hash)
            return {"valid": False, "error": "Transaction not found or invalid"}
        if receipt.get("status") != "0x1":
            remove_tx_hash_reservation(tx_hash)
            return {"valid": False, "error": "Transaction reverted"}

        # S5 — Verify transaction is recent (block timestamp < MAX_TX_AGE_SECONDS ago)
        block_hex = receipt.get("blockNumber")
        if block_hex:
            block_payload = {
                "jsonrpc": "2.0", "id": 2,
                "method": "eth_getBlockByNumber", "params": [block_hex, False],
            }
            async with httpx.AsyncClient(timeout=15) as client:
                block_resp = await client.post(rpc_url, json=block_payload)
            block_result = block_resp.json().get("result")
            if block_result:
                block_ts = int(block_result.get("timestamp", "0x0"), 16)
                if time.time() - block_ts > MAX_TX_AGE_SECONDS:
                    remove_tx_hash_reservation(tx_hash)
                    return {"valid": False, "error": f"Transaction too old (>{MAX_TX_AGE_SECONDS}s). Only recent transactions accepted."}

        expected_raw = int(expected_amount * (10 ** USDC_DECIMALS))
        for log_entry in receipt.get("logs", []):
            if log_entry.get("address", "").lower() != usdc_contract.lower():
                continue
            topics = log_entry.get("topics", [])
            if len(topics) < 3 or topics[0].lower() != TRANSFER_TOPIC:
                continue
            to_addr = "0x" + topics[2][-40:]
            if to_addr.lower() != WALLET_ADDRESS:
                continue

            # S7 — Verify sender matches expected payer using timing-safe comparison
            from_addr = "0x" + topics[1][-40:]
            if expected_sender:
                expected_addr = expected_sender.strip().lower()
                if not hmac.compare_digest(from_addr.lower(), expected_addr):
                    remove_tx_hash_reservation(tx_hash)
                    return {"valid": False, "error": f"Payment sender mismatch: expected {expected_sender}, got {from_addr}"}

            raw_amount = int(log_entry.get("data", "0x0"), 16)
            if raw_amount >= expected_raw:
                return {"valid": True, "error": None}
            got = raw_amount / (10 ** USDC_DECIMALS)
            remove_tx_hash_reservation(tx_hash)
            return {"valid": False, "error": f"Insufficient payment: expected {expected_amount} USDC, got {got}"}

        remove_tx_hash_reservation(tx_hash)
        return {"valid": False, "error": "No matching USDC transfer found in transaction"}
    except Exception as exc:
        # On any error, release the reserved hash
        remove_tx_hash_reservation(tx_hash)
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
                # Build the networks list from CHAINS for agent discoverability
                networks = [
                    {
                        "chain": key,
                        "label": cfg["label"],
                        "chain_id": cfg["chain_id"],
                        "usdc_contract": cfg["usdc_contract"],
                        "rpc_url": cfg["rpc_url"],
                        "gas": cfg["gas"],
                        "explorer": cfg["explorer"],
                    }
                    for key, cfg in CHAINS.items()
                ]
                default_cfg = CHAINS[DEFAULT_CHAIN]
                return JSONResponse(status_code=402, content={
                    "error": "Payment Required",
                    "payment_details": {
                        "amount": str(price), "currency": "USDC",
                        "network": default_cfg["label"],
                        "chain_id": default_cfg["chain_id"],
                        "recipient": WALLET_ADDRESS,
                        "usdc_contract": default_cfg["usdc_contract"],
                        "rpc_url": default_cfg["rpc_url"],
                        "networks": networks,
                        "instructions": (
                            f"Send USDC on {default_cfg['label']} to the recipient address, "
                            "then retry with headers X-Payment-TxHash: 0x... and X-Payer-Address: 0x... "
                            "Optionally add X-Payment-Chain: base|skale to select the network."
                        ),
                    },
                })

            # Determine chain from header (default to DEFAULT_CHAIN)
            payment_chain = request.headers.get("X-Payment-Chain", DEFAULT_CHAIN).lower()

            # S7 — Verify sender address if provided
            payer_address = request.headers.get("X-Payer-Address")
            check = await verify_payment(tx_hash, price, expected_sender=payer_address, chain=payment_chain)
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
async def _register_on_marketplace():
    """Auto-register all paid endpoints on x402 Bazaar at startup."""
    if not BAZAAR_REGISTRY_URL:
        logger.warning("Marketplace registration skipped: BAZAAR_REGISTRY_URL not set")
        return
    async with httpx.AsyncClient(timeout=10) as client:
        for entry in PAYWALL_REGISTRY:
            payload = {
                "name": entry["name"],
                "url": f"{API_BASE_URL.rstrip('/')}{entry['path']}",
                "price": entry["price"], "currency": "USDC",
                "network": CHAINS[DEFAULT_CHAIN]["label"],
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
