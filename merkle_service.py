"""
merkle_service.py — Merkle Tree 生成与 Proof 查询服务

功能：
  1. 从数据库拉取所有信誉分 >= 20 且已绑定钱包的用户
  2. 构建 (address, score) 的 Merkle Tree
  3. 生成 root hash（管理员上链用）
  4. 为单个用户生成 Merkle Proof（前端 Mint SBT 用）

Leaf 编码规则（与 Solidity 合约完全一致）：
  leaf = keccak256(abi.encodePacked(address, uint64(score)))

依赖：web3 (用 solidityKeccak)
"""

from __future__ import annotations

import json
import math
import os
from typing import Optional

from web3 import Web3


# ─── Leaf 编码 ────────────────────────────────────────────

def _encode_leaf(address: str, score: int) -> bytes:
    """
    编码与 Solidity 的 keccak256(abi.encodePacked(address, uint64(score))) 完全一致。
    """
    return Web3.solidity_keccak(
        ["address", "uint64"],
        [Web3.to_checksum_address(address), score],
    )


def _hash_pair(a: bytes, b: bytes) -> bytes:
    """
    对两个节点排序后哈希（与 OpenZeppelin MerkleProof 库一致）。
    排序保证了 proof 验证的顺序无关性。
    """
    if a <= b:
        return Web3.solidity_keccak(["bytes32", "bytes32"], [a, b])
    else:
        return Web3.solidity_keccak(["bytes32", "bytes32"], [b, a])


# ─── Merkle Tree 类 ──────────────────────────────────────

class MerkleTree:
    """
    完整的二叉 Merkle Tree 实现。
    支持任意数量的叶子节点（不足 2^n 时自动补齐）。
    """

    def __init__(self, leaves: list[bytes]):
        """
        :param leaves: 已编码的叶子哈希列表
        """
        if not leaves:
            raise ValueError("MerkleTree: leaves cannot be empty")

        self._leaves = sorted(leaves)  # 排序保证确定性
        self._layers: list[list[bytes]] = [self._leaves]
        self._build()

    def _build(self):
        """自底向上构建所有层。"""
        current = self._layers[0]
        while len(current) > 1:
            next_layer = []
            for i in range(0, len(current), 2):
                if i + 1 < len(current):
                    next_layer.append(_hash_pair(current[i], current[i + 1]))
                else:
                    # 奇数个节点：最后一个提升到上层
                    next_layer.append(current[i])
            self._layers.append(next_layer)
            current = next_layer

    @property
    def root(self) -> bytes:
        """返回 Merkle Root（bytes32）。"""
        return self._layers[-1][0]

    @property
    def root_hex(self) -> str:
        """返回 0x 前缀的十六进制 root。"""
        return "0x" + self.root.hex()

    def get_proof(self, leaf: bytes) -> list[bytes]:
        """
        获取指定叶子的 Merkle Proof。
        :return: bytes32[] proof 数组
        :raises ValueError: 叶子不在树中
        """
        if leaf not in self._leaves:
            raise ValueError("MerkleTree: leaf not found in tree")

        idx = self._leaves.index(leaf)
        proof = []

        for layer in self._layers[:-1]:  # 遍历除 root 层之外的所有层
            pair_idx = idx ^ 1  # 兄弟节点索引
            if pair_idx < len(layer):
                proof.append(layer[pair_idx])
            idx //= 2

        return proof

    def get_proof_hex(self, leaf: bytes) -> list[str]:
        """返回 0x 前缀十六进制格式的 proof 数组。"""
        return ["0x" + p.hex() for p in self.get_proof(leaf)]

    @property
    def leaf_count(self) -> int:
        return len(self._leaves)


# ─── 高级接口：从数据库生成 Tree ────────────────────────

def build_merkle_tree_from_db(app) -> tuple[Optional[MerkleTree], list[dict]]:
    """
    从 Flask app 上下文中读取数据库，构建 Merkle Tree。

    :param app: Flask application instance
    :return: (MerkleTree 实例或 None, 合格用户列表)

    合格用户条件：
      - reputation_score >= 20 (bronzeThreshold)
      - 已绑定钱包 (wallet_link 存在且有 address)
      - 非管理员
      - 未被拉黑
    """
    from models import User, WalletLink

    with app.app_context():
        eligible = (
            User.query
            .join(WalletLink, User.id == WalletLink.user_id)
            .filter(
                User.reputation_score >= 20,
                User.user_type != "admin",
                User.is_blacklisted == False,  # noqa: E712
            )
            .all()
        )

        if not eligible:
            return None, []

        entries = []
        leaves = []
        for user in eligible:
            wallet = user.wallet_link
            if not wallet or not wallet.address:
                continue
            addr = Web3.to_checksum_address(wallet.address)
            score = int(user.reputation_score)
            leaf = _encode_leaf(addr, score)
            entries.append({
                "user_id": user.id,
                "username": user.username,
                "address": addr,
                "score": score,
                "leaf_hex": "0x" + leaf.hex(),
            })
            leaves.append(leaf)

        if not leaves:
            return None, []

        tree = MerkleTree(leaves)
        return tree, entries


def get_user_proof(app, user_id: int) -> Optional[dict]:
    """
    为指定用户生成 Merkle Proof。

    :return: {
        "address": "0x...",
        "score": 42,
        "proof": ["0x...", "0x...", ...],
        "leaf": "0x...",
        "root": "0x..."
    } 或 None（用户不合格）
    """
    from models import User, WalletLink

    with app.app_context():
        user = User.query.get(user_id)
        if not user or not user.wallet_link or not user.wallet_link.address:
            return None
        if user.reputation_score < 20 or user.is_blacklisted:
            return None

        tree, entries = build_merkle_tree_from_db(app)
        if tree is None:
            return None

        addr = Web3.to_checksum_address(user.wallet_link.address)
        score = int(user.reputation_score)
        leaf = _encode_leaf(addr, score)

        try:
            proof = tree.get_proof_hex(leaf)
        except ValueError:
            return None

        return {
            "address": addr,
            "score": score,
            "proof": proof,
            "leaf": "0x" + leaf.hex(),
            "root": tree.root_hex,
        }


def update_merkle_root_onchain(app) -> dict:
    """
    构建最新 Merkle Tree 并调用合约 updateMerkleRoot。

    :return: {
        "success": bool,
        "root": "0x...",
        "tx_hash": "0x...",
        "eligible_count": int,
        "error": str (仅失败时)
    }
    """
    from web3 import Web3 as W3

    tree, entries = build_merkle_tree_from_db(app)
    if tree is None:
        return {"success": False, "error": "No eligible users found", "eligible_count": 0}

    root_hex = tree.root_hex

    with app.app_context():
        rpc_url = app.config.get("ETH_RPC_URL")
        private_key = app.config.get("ETH_SIGNER_PRIVATE_KEY")
        sbt_address = app.config.get("SBT_CONTRACT_ADDRESS")

        if not sbt_address:
            return {"success": False, "error": "SBT_CONTRACT_ADDRESS not configured", "eligible_count": len(entries)}

        w3 = W3(W3.HTTPProvider(rpc_url))
        if not w3.is_connected():
            return {"success": False, "error": "Cannot connect to Ethereum RPC", "eligible_count": len(entries)}

        # 加载 ABI
        abi_path = os.path.join(os.path.dirname(__file__), "contracts", "abi", "ReputationSBT.json")
        with open(abi_path, "r") as f:
            sbt_abi = json.load(f)

        contract = w3.eth.contract(
            address=W3.to_checksum_address(sbt_address),
            abi=sbt_abi,
        )

        account = w3.eth.account.from_key(private_key)
        nonce = w3.eth.get_transaction_count(account.address, "pending")

        tx = contract.functions.updateMerkleRoot(
            bytes.fromhex(root_hex[2:])  # 去掉 0x 前缀
        ).build_transaction({
            "from": account.address,
            "nonce": nonce,
            "gas": 100_000,
            "gasPrice": w3.eth.gas_price,
            "chainId": int(app.config.get("ETH_CHAIN_ID", 11155111)),
        })

        signed = w3.eth.account.sign_transaction(tx, private_key)
        try:
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        except Exception as e:
            err_msg = str(e)
            if "already known" in err_msg:
                return {"success": False, "error": "交易已提交，请等待上一笔确认后再试（约15-30秒）", "eligible_count": len(entries)}
            if "nonce too low" in err_msg:
                return {"success": False, "error": "Nonce 冲突，请稍后重试", "eligible_count": len(entries)}
            if "insufficient funds" in err_msg:
                return {"success": False, "error": "签名账户 Sepolia ETH 余额不足，请先领取测试币", "eligible_count": len(entries)}
            return {"success": False, "error": f"发送交易失败: {err_msg[:200]}", "eligible_count": len(entries)}

        # 可选：等待确认
        wait = app.config.get("ETH_WAIT_FOR_RECEIPT", False)
        if wait:
            try:
                receipt = w3.eth.wait_for_transaction_receipt(
                    tx_hash,
                    timeout=int(app.config.get("ETH_TX_TIMEOUT_SECONDS", 180)),
                )
            except Exception:
                pass

        return {
            "success": True,
            "root": root_hex,
            "tx_hash": "0x" + tx_hash.hex(),
            "eligible_count": len(entries),
            "entries": entries,
        }
