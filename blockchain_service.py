import json
import hashlib
from datetime import datetime, timezone
from typing import List, Optional

from flask import current_app

from extensions import db
from models import Block, Statement
from web3_service import submit_anchor_transaction

# Configuration: how many statements per block
DEFAULT_BLOCK_SIZE = 10


def _calc_block_hash(index: int, prev_hash: Optional[str], statements: List[Statement], created_at: datetime) -> str:
    payload = {
        "index": index,
        "prev_hash": prev_hash or "",
        "created_at": created_at.isoformat(),
        "statements": [
            {
                "id": s.id,
                "kind": s.kind,
                "user_id": s.user_id,
                "created_at": s.created_at.isoformat(),
                "payload": s.payload,
            }
            for s in statements
        ],
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _get_next_index_and_prev_hash() -> (int, Optional[str]):
    last: Optional[Block] = (
        db.session.query(Block).order_by(Block.index.desc()).limit(1).one_or_none()
    )
    if last is None:
        return 0, None
    return last.index + 1, last.hash


def append_statement(kind: str, payload: dict, user_id: Optional[int] = None) -> Statement:
    """Create a new statement record. Does not immediately create a block.
    After appending, call maybe_seal_block().
    """
    st = Statement(kind=kind, payload=payload, user_id=user_id)
    db.session.add(st)
    db.session.commit()
    return st


def anchor_block(block: Block, statement_count: int) -> Optional[dict]:
    if not bool(current_app.config.get("BLOCKCHAIN_ANCHOR_AUTO", False)):
        return None

    payload = {
        "source": "dailyhelper_internal_block",
        "block_id": block.id,
        "block_index": block.index,
        "block_hash": block.hash,
        "statement_count": statement_count,
        "sealed_at": block.created_at.isoformat() + "Z",
    }
    anchor_text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    try:
        tx_result = submit_anchor_transaction(anchor_text)
        append_statement(
            kind="block_anchor_submitted",
            payload={
                **payload,
                "tx_hash": tx_result.get("tx_hash"),
                "chain_id": tx_result.get("chain_id"),
                "tx_status": tx_result.get("status"),
                "tx_url": tx_result.get("tx_url"),
                "tx_block_number": tx_result.get("block_number"),
            },
            user_id=None,
        )
        return tx_result
    except Exception as e:
        append_statement(
            kind="block_anchor_failed",
            payload={
                **payload,
                "error": str(e)[:500],
            },
            user_id=None,
        )
        return None


def maybe_seal_block(limit: Optional[int] = None) -> Optional[Block]:
    """Seal a new block if there are at least `limit` unsealed statements.
    Returns the new Block or None if not enough statements.
    """
    size = limit or int(current_app.config.get("BLOCK_SIZE", DEFAULT_BLOCK_SIZE))

    # Unsealed statements
    unsealed: List[Statement] = (
        db.session.query(Statement).filter(Statement.block_id.is_(None)).order_by(Statement.id.asc()).limit(size).all()
    )
    if len(unsealed) < size:
        return None

    index, prev_hash = _get_next_index_and_prev_hash()
    created_at = datetime.now(timezone.utc)
    digest = _calc_block_hash(index, prev_hash, unsealed, created_at)

    block = Block(index=index, prev_hash=prev_hash, hash=digest, created_at=created_at)
    db.session.add(block)
    db.session.flush()  # get block.id

    for s in unsealed:
        s.block_id = block.id
    db.session.commit()
    anchor_block(block, statement_count=len(unsealed))
    return block
