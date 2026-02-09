# x402 Fast Monetization Template -- SPECS

**Version:** 1.0
**Date:** 2026-02-09
**Auteur:** Product Owner
**Statut:** APPROVED

---

## 1. Vision

Permettre a un developpeur Python de transformer n'importe quelle fonction en API payante (protocole HTTP 402, paiement USDC on-chain sur Base) en moins de 5 minutes, avec un seul fichier `main.py` et un decorator `@x402_paywall`.

---

## 2. User Stories (format Gherkin)

### US-1 : Monetiser une fonction avec le decorator

```gherkin
Feature: Decorator @x402_paywall
  En tant que developpeur Python,
  Je veux ajouter un decorator @x402_paywall(price=0.05) sur ma fonction,
  Afin qu'elle devienne automatiquement un endpoint FastAPI payant.

  Scenario: Fonction decoree devient un endpoint GET
    Given une fonction Python "generate_qr(text: str) -> bytes"
    And le decorator @x402_paywall(price=0.05) est applique
    When le serveur FastAPI demarre
    Then un endpoint GET /generate_qr est disponible
    And il apparait dans la documentation Swagger a /docs

  Scenario: Fonction avec type hint dict retourne du JSON
    Given une fonction Python "get_joke() -> dict"
    And le decorator @x402_paywall(price=0.01) est applique
    When un client appelle GET /get_joke sans paiement
    Then le serveur repond HTTP 402
    And le body contient les payment_details (amount, recipient, network, currency)

  Scenario: Fonction avec type hint bytes retourne une image
    Given une fonction Python "generate_qr(text: str) -> bytes"
    And le decorator @x402_paywall(price=0.05) est applique
    When un client appelle GET /generate_qr?text=hello avec un X-Payment-TxHash valide
    Then le serveur retourne HTTP 200 avec Content-Type image/png
```

### US-2 : Paiement et verification on-chain

```gherkin
Feature: Protocole x402 -- Verification de paiement
  En tant que serveur API,
  Je veux verifier les paiements USDC on-chain sur Base,
  Afin de ne servir que les clients qui ont paye.

  Scenario: Requete sans paiement -> 402
    Given un endpoint protege par @x402_paywall(price=0.05)
    When un client fait GET /generate_qr?text=hello sans header X-Payment-TxHash
    Then le serveur repond HTTP 402 Payment Required
    And le body JSON contient:
      | champ                        | valeur                                      |
      | payment_details.amount       | "0.05"                                      |
      | payment_details.currency     | "USDC"                                      |
      | payment_details.network      | "Base"                                      |
      | payment_details.recipient    | la valeur de WALLET_ADDRESS du .env          |
      | payment_details.rpc_url      | "https://mainnet.base.org"                  |
      | payment_details.usdc_contract| "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"|

  Scenario: Requete avec tx hash valide -> 200
    Given un client a paye 0.05 USDC au wallet du serveur sur Base
    And la transaction est confirmee on-chain (status=1)
    When le client fait GET /generate_qr?text=hello avec header X-Payment-TxHash: 0xabc123...
    Then le serveur verifie via Base RPC:
      - le statut de la transaction (status == 1, revert == false)
      - le destinataire du transfert USDC == WALLET_ADDRESS
      - le montant transfere >= price de l'endpoint
    And le serveur execute la fonction generate_qr("hello")
    And le serveur retourne HTTP 200 avec le resultat

  Scenario: Requete avec tx hash invalide -> 402
    Given un client envoie un header X-Payment-TxHash avec un hash inexistant
    When le serveur tente de verifier la transaction via Base RPC
    Then le serveur repond HTTP 402 avec un message d'erreur "Transaction not found or invalid"

  Scenario: Requete avec montant insuffisant -> 402
    Given un client a paye 0.01 USDC mais l'endpoint coute 0.05
    When le client envoie le tx hash
    Then le serveur repond HTTP 402 avec un message "Insufficient payment: expected 0.05 USDC, got 0.01"

  Scenario: Protection anti-replay
    Given un tx hash a deja ete utilise pour un appel precedent
    When un client reutilise le meme tx hash
    Then le serveur repond HTTP 402 avec un message "Transaction already used"
```

### US-3 : Auto-registration sur la marketplace

```gherkin
Feature: Auto-registration sur x402 Bazaar
  En tant que developpeur,
  Je veux que mes endpoints soient automatiquement enregistres sur la marketplace,
  Afin que les agents IA puissent les decouvrir.

  Scenario: Enregistrement au demarrage
    Given le serveur demarre avec BAZAAR_REGISTRY_URL et API_BASE_URL configures
    When l'event FastAPI "startup" se declenche
    Then le serveur envoie un POST a BAZAAR_REGISTRY_URL/api/register pour chaque endpoint
    And le payload contient: name, url, price, currency, description, tags

  Scenario: Variable BAZAAR_REGISTRY_URL absente
    Given BAZAAR_REGISTRY_URL n'est pas defini dans le .env
    When le serveur demarre
    Then le serveur affiche un warning "Marketplace registration skipped: BAZAAR_REGISTRY_URL not set"
    And le serveur continue de fonctionner normalement (registration optionnelle)
```

### US-4 : Deploiement one-click sur Replit

```gherkin
Feature: Deploiement Replit
  En tant que developpeur,
  Je veux forker le template sur Replit et le lancer en un clic,
  Afin de ne pas gerer d'infrastructure.

  Scenario: Fork et Run sur Replit
    Given le repo contient un fichier .replit et replit.nix
    When un utilisateur clique "Run" sur Replit
    Then pip installe les dependances depuis requirements.txt
    And uvicorn demarre le serveur sur le port 8000
    And les endpoints sont accessibles via l'URL publique Replit
```

### US-5 : Execution locale

```gherkin
Feature: Execution locale
  En tant que developpeur,
  Je veux lancer le template en local avec "python main.py",
  Afin de tester avant de deployer.

  Scenario: Lancement local
    Given le developpeur a clone le repo
    And il a installe les dependances: pip install -r requirements.txt
    And il a cree un fichier .env avec WALLET_ADDRESS
    When il execute "python main.py"
    Then uvicorn demarre sur http://0.0.0.0:8000
    And la doc Swagger est accessible a http://localhost:8000/docs
```

---

## 3. Architecture du fichier main.py

Le fichier `main.py` est le SEUL fichier de code du projet. Il contient tout dans un seul fichier, organise en sections clairement delimitees par des commentaires.

```
main.py (~ 200-250 lignes)
|
|-- SECTION 1: Imports et Configuration
|   - FastAPI, uvicorn, httpx, dotenv, os, functools, json, hashlib
|   - Chargement du .env
|   - Constants: USDC_CONTRACT, BASE_RPC_URL, CHAIN_ID
|   - Variables d'env: WALLET_ADDRESS, BAZAAR_REGISTRY_URL, API_BASE_URL
|
|-- SECTION 2: Payment Verification Engine
|   - used_tx_hashes: set()  (anti-replay en memoire)
|   - async def verify_payment(tx_hash: str, expected_amount: float) -> bool
|       * Appel JSON-RPC eth_getTransactionReceipt via Base RPC
|       * Decode le log Transfer de l'ERC-20 USDC
|       * Verifie: status==1, to==WALLET_ADDRESS, amount>=expected, hash pas deja utilise
|       * Ajoute le hash au set si valide
|       * Retourne True/False
|
|-- SECTION 3: Decorator @x402_paywall
|   - def x402_paywall(price: float, description: str = "", tags: list[str] = [])
|       * Enregistre la fonction dans un registre interne (PAYWALL_REGISTRY)
|       * Cree une route FastAPI GET avec le nom de la fonction comme path
|       * Les parametres de la fonction deviennent les query params
|       * Si pas de header X-Payment-TxHash -> 402 avec payment_details
|       * Si header present -> verify_payment() -> execute la fonction -> 200
|       * Detecte le type de retour (dict->JSON, bytes->image, str->text)
|
|-- SECTION 4: Marketplace Registration
|   - async def register_on_marketplace()
|       * Parcourt PAYWALL_REGISTRY
|       * POST chaque endpoint vers BAZAAR_REGISTRY_URL/api/register
|   - Attache sur l'event @app.on_event("startup")
|
|-- SECTION 5: Exemples (3 fonctions)
|   - @x402_paywall(price=0.05, description="Generate QR code from text", tags=["qr", "image"])
|     def generate_qr(text: str) -> bytes
|
|   - @x402_paywall(price=0.03, description="Summarize text using simple extraction", tags=["text", "nlp"])
|     def summarize(text: str, max_sentences: int = 3) -> dict
|
|   - @x402_paywall(price=0.01, description="Get a random joke", tags=["fun", "text"])
|     def random_joke() -> dict
|
|-- SECTION 6: Health Check & Entry Point
|   - GET / -> { "service": "x402 API", "endpoints": [...], "docs": "/docs" }
|   - GET /health -> { "status": "ok" }
|   - if __name__ == "__main__": uvicorn.run(app, host="0.0.0.0", port=8000)
```

---

## 4. Endpoints

| Methode | Path          | Prix (USDC) | Description                        | Params                          | Retour         |
|---------|---------------|-------------|------------------------------------|---------------------------------|----------------|
| GET     | /             | Gratuit     | Page d'accueil / index des APIs    | -                               | JSON           |
| GET     | /health       | Gratuit     | Health check                       | -                               | JSON           |
| GET     | /docs         | Gratuit     | Swagger UI (auto FastAPI)          | -                               | HTML           |
| GET     | /generate_qr  | 0.05 USDC   | Genere un QR code PNG              | text: str (query)               | image/png      |
| GET     | /summarize    | 0.03 USDC   | Resume un texte (extraction)       | text: str, max_sentences: int=3 | JSON           |
| GET     | /random_joke  | 0.01 USDC   | Retourne une blague aleatoire      | -                               | JSON           |

### Format de la reponse 402

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

### Format de la reponse 200 (JSON)

```json
{
  "result": { ... },
  "payment": {
    "tx_hash": "0xabc...",
    "amount_charged": "0.05",
    "currency": "USDC"
  }
}
```

---

## 5. Variables d'environnement

| Variable              | Obligatoire | Defaut                          | Description                                      |
|-----------------------|-------------|---------------------------------|--------------------------------------------------|
| WALLET_ADDRESS        | OUI         | -                               | Adresse Ethereum du producteur (recoit les USDC) |
| BASE_RPC_URL          | NON         | https://mainnet.base.org        | URL du noeud RPC Base pour verifier les tx        |
| BAZAAR_REGISTRY_URL   | NON         | https://x402-api.onrender.com   | URL de la marketplace pour auto-registration      |
| API_BASE_URL          | NON         | http://localhost:8000           | URL publique de cette API (pour la marketplace)   |
| PORT                  | NON         | 8000                            | Port d'ecoute du serveur                          |

Fichier `.env.example` :

```env
# REQUIRED: Your Ethereum wallet address to receive USDC payments
WALLET_ADDRESS=0xYOUR_WALLET_ADDRESS_HERE

# OPTIONAL: Base RPC endpoint (default: https://mainnet.base.org)
# BASE_RPC_URL=https://mainnet.base.org

# OPTIONAL: x402 Bazaar marketplace URL for auto-registration
# BAZAAR_REGISTRY_URL=https://x402-api.onrender.com

# OPTIONAL: Public URL of your API (used for marketplace registration)
# API_BASE_URL=https://your-replit-url.repl.co

# OPTIONAL: Server port (default: 8000)
# PORT=8000
```

---

## 6. Dependances Python

Fichier `requirements.txt` :

| Package       | Version   | Raison                                              |
|---------------|-----------|-----------------------------------------------------|
| fastapi       | >=0.104.0 | Framework web async avec auto-documentation Swagger  |
| uvicorn       | >=0.24.0  | Serveur ASGI pour FastAPI                            |
| httpx         | >=0.25.0  | Client HTTP async pour appels RPC et registration    |
| python-dotenv | >=1.0.0   | Chargement des variables depuis .env                 |
| qrcode        | >=7.4     | Generation de QR codes (exemple generate_qr)         |
| Pillow        | >=10.0.0  | Manipulation d'images pour export QR en PNG          |

**Pas de dependance a un LLM ou API externe** pour le summarizer : on utilise un algorithme extractif simple (split par phrases, scoring par frequence de mots).

---

## 7. Structure du projet

```
x402-fast-monetization-template/
|-- main.py               # Le "Golden Script" -- SEUL fichier de code
|-- requirements.txt      # Dependances Python
|-- .env.example          # Template de configuration
|-- .replit               # Configuration Replit (run command)
|-- replit.nix            # Dependances systeme Replit
|-- README.md             # Guide "3 etapes pour monetiser"
|-- SPECS.md              # Ce fichier
```

---

## 8. Regles metier et contraintes techniques

### 8.1 Verification de paiement

- La verification se fait via `eth_getTransactionReceipt` sur le RPC Base.
- On decode les logs de l'event `Transfer(address,address,uint256)` du contrat USDC.
- Le topic du Transfer event est `0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef`.
- USDC sur Base a 6 decimales : 0.05 USDC = 50000 unites.
- On verifie : `status == 1` (tx reussie), `to == WALLET_ADDRESS` (bon destinataire), `value >= expected_amount` (montant suffisant).
- Anti-replay : un `set()` en memoire stocke les tx hash deja utilises. Chaque hash ne peut etre utilise qu'une seule fois. Ceci est volontairement simple (pas de persistence) pour garder le template minimal.

### 8.2 Decorator @x402_paywall

- Le decorator accepte les parametres : `price` (float, obligatoire), `description` (str, optionnel), `tags` (list[str], optionnel).
- Le nom de la fonction Python devient le path de l'endpoint (prefixe par `/`).
- Les parametres de la fonction (type hints) deviennent les query parameters de l'endpoint.
- Le type de retour determine le Content-Type de la reponse :
  - `dict` -> `application/json`
  - `bytes` -> `image/png` (avec header Content-Type adapte)
  - `str` -> `text/plain`
- Les fonctions decorees peuvent etre sync ou async.

### 8.3 Registration marketplace

- La registration est optionnelle et silencieuse en cas d'echec (warning dans les logs).
- Payload POST vers `/api/register` :
  ```json
  {
    "name": "generate_qr",
    "url": "https://your-api.com/generate_qr",
    "price": "0.05",
    "currency": "USDC",
    "network": "Base",
    "description": "Generate QR code from text",
    "tags": ["qr", "image"],
    "protocol": "x402"
  }
  ```

### 8.4 Compatibilite Replit

- Le fichier `.replit` doit specifier : `run = "python main.py"`
- Le fichier `replit.nix` doit inclure Python 3.11+.
- Le serveur ecoute sur `0.0.0.0` (pas `127.0.0.1`) pour que Replit puisse router le trafic.

---

## 9. Criteres de qualite (Definition of Done)

- [ ] `python main.py` demarre sans erreur avec seulement WALLET_ADDRESS configure
- [ ] GET / retourne la liste des endpoints disponibles
- [ ] GET /docs affiche le Swagger UI avec les 3 endpoints payants
- [ ] GET /generate_qr?text=hello sans header -> HTTP 402 avec payment_details complet
- [ ] GET /generate_qr?text=hello avec X-Payment-TxHash valide -> HTTP 200 + image PNG
- [ ] GET /summarize?text=... avec paiement valide -> HTTP 200 + JSON avec resume
- [ ] GET /random_joke avec paiement valide -> HTTP 200 + JSON avec blague
- [ ] Un tx hash deja utilise retourne HTTP 402 "Transaction already used"
- [ ] Un tx hash avec montant insuffisant retourne HTTP 402 avec message explicite
- [ ] Si BAZAAR_REGISTRY_URL est configure, les endpoints sont enregistres au demarrage
- [ ] Si BAZAAR_REGISTRY_URL est absent, le serveur demarre quand meme avec un warning
- [ ] Le template fonctionne sur Replit avec "Run" sans configuration supplementaire
- [ ] Le fichier main.py fait moins de 300 lignes
- [ ] Aucune dependance a un service externe pour les fonctions exemples (pas de LLM API)

---

## 10. Hors scope (v1)

- Authentification par API key
- Support POST (uniquement GET en v1)
- Persistence des tx hash utilisees (en memoire seulement)
- Support d'autres cryptomonnaies que USDC
- Support d'autres reseaux que Base
- Dashboard de revenus
- Rate limiting
- Tests unitaires (a ajouter en v2)
