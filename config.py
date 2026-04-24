import os

class Config:
    """Base configuration for the Flask application."""

    # Security
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-in-production")

    # Database
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///app.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Flask-WTF
    WTF_CSRF_ENABLED = True

    # Logging
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

    # Web3 / Blockchain
    ETH_RPC_URL = os.environ.get("ETH_RPC_URL", "")
    ETH_CHAIN_NAME = os.environ.get("ETH_CHAIN_NAME", "sepolia")
    ETH_CHAIN_ID = os.environ.get("ETH_CHAIN_ID", "11155111")
    ETH_SIGNER_PRIVATE_KEY = os.environ.get("ETH_SIGNER_PRIVATE_KEY", "")
    ETH_ANCHOR_TARGET_ADDRESS = os.environ.get("ETH_ANCHOR_TARGET_ADDRESS", "")
    ETH_ANCHOR_GAS_LIMIT = int(os.environ.get("ETH_ANCHOR_GAS_LIMIT", "120000"))
    ETH_GAS_PRICE_MULTIPLIER = float(os.environ.get("ETH_GAS_PRICE_MULTIPLIER", "1.0"))
    ETH_WAIT_FOR_RECEIPT = os.environ.get("ETH_WAIT_FOR_RECEIPT", "true").strip().lower() in {"1", "true", "yes", "on"}
    ETH_TX_TIMEOUT_SECONDS = int(os.environ.get("ETH_TX_TIMEOUT_SECONDS", "180"))
    ETH_EXPLORER_TX_BASE_URL = os.environ.get("ETH_EXPLORER_TX_BASE_URL", "https://sepolia.etherscan.io/tx")
    BLOCKCHAIN_ANCHOR_AUTO = os.environ.get("BLOCKCHAIN_ANCHOR_AUTO", "true").strip().lower() in {"1", "true", "yes", "on"}
    # Internal blockchain batching (number of statements per block)
    BLOCK_SIZE = int(os.environ.get("BLOCK_SIZE", "10"))

    # Smart Contracts (deployed on Sepolia)
    SBT_CONTRACT_ADDRESS = os.environ.get("SBT_CONTRACT_ADDRESS", "0xC80713Ae1aB233BB29b9991a80BA7594f5C128F3")
    ESCROW_CONTRACT_ADDRESS = os.environ.get("ESCROW_CONTRACT_ADDRESS", "0x90413AfD18C53172d09caD650FB5Fd80b7154002")
    DAO_VOTE_THRESHOLD = int(os.environ.get("DAO_VOTE_THRESHOLD", "1"))  # 测试环境默认 1 票

    # Kimi (Moonshot) AI chatbot
    KIMI_API_KEY = os.environ.get("KIMI_API_KEY", "")
    KIMI_MODEL = os.environ.get("KIMI_MODEL", "moonshot-v1-8k")
