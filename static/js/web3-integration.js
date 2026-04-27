/**
 * web3-integration.js — DailyHelper 智能合约前端交互
 *
 * 依赖：ethers.js v6 (通过 CDN 引入)
 *
 * 功能：
 *   1. SBT Mint / 升级（个人主页）
 *   2. Escrow 资金锁定（接受提议时）
 *   3. Escrow 释放资金（确认完成时）
 *   4. Escrow 发起仲裁
 */

// ─── 全局配置（由后端 /api/contracts/config 注入）─────────
let CONTRACT_CONFIG = null;

async function loadContractConfig() {
  if (CONTRACT_CONFIG) return CONTRACT_CONFIG;
  try {
    const resp = await fetch("/api/contracts/config");
    CONTRACT_CONFIG = await resp.json();
    return CONTRACT_CONFIG;
  } catch (e) {
    console.error("Failed to load contract config:", e);
    return null;
  }
}

// ─── ABI 精简版 ──────────────────────────────────────────

const SBT_ABI = [
  "function mintOrUpgradeSBT(uint64 score, bytes32[] calldata proof) external",
  "function getSBT(address account) external view returns (uint256,uint8,uint64,uint64,uint64)",
  "function tierOf(address account) external view returns (uint8)",
  "function merkleRoot() external view returns (bytes32)"
];

const ESCROW_ABI = [
  "function createEscrow(uint256 taskId, address helper) external payable",
  "function releaseToHelper(uint256 taskId) external",
  "function raiseDispute(uint256 taskId) external",
  "function getEscrow(uint256 taskId) external view returns (address,address,uint256,uint8,uint64,uint64,uint32,uint32)",
  "event EscrowCreated(uint256 indexed taskId, address indexed requester, address indexed helper, uint256 amount)",
  "event EscrowReleased(uint256 indexed taskId, address indexed helper, uint256 amount)",
  "event DisputeRaised(uint256 indexed taskId, address indexed raisedBy)"
];

const TIER_NAMES = ["无", "🥉 铜牌", "🥈 银牌", "🥇 金牌"];

// ─── 工具函数 ────────────────────────────────────────────

async function ensureCorrectNetwork(provider) {
  const cfg = await loadContractConfig();
  if (!cfg) throw new Error("无法加载合约配置");
  const network = await provider.getNetwork();
  if (Number(network.chainId) !== cfg.chain_id) {
    try {
      await window.ethereum.request({
        method: "wallet_switchEthereumChain",
        params: [{ chainId: "0x" + cfg.chain_id.toString(16) }],
      });
    } catch (e) {
      throw new Error(`请切换 MetaMask 到 Sepolia 测试网 (Chain ID: ${cfg.chain_id})`);
    }
  }
}

async function getSignerAndContracts() {
  if (!window.ethereum) throw new Error("请安装 MetaMask");
  const provider = new ethers.BrowserProvider(window.ethereum);
  await ensureCorrectNetwork(provider);
  const signer = await provider.getSigner();
  const cfg = await loadContractConfig();

  const contracts = {};
  if (cfg.sbt_contract) {
    contracts.sbt = new ethers.Contract(cfg.sbt_contract, SBT_ABI, signer);
  }
  if (cfg.escrow_contract) {
    contracts.escrow = new ethers.Contract(cfg.escrow_contract, ESCROW_ABI, signer);
  }
  return { signer, contracts, config: cfg };
}

// 通知后端同步状态
async function syncEscrowStatus(taskId, action, txHash) {
  const resp = await fetch("/api/escrow/sync", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_id: taskId, action: action, tx_hash: txHash }),
  });
  if (!resp.ok) {
    let message = "后端同步 Escrow 状态失败";
    try {
      const data = await resp.json();
      message = data.error || message;
    } catch (e) {
      message = await resp.text();
    }
    throw new Error(message);
  }
  return await resp.json();
}

async function ensureVerifiedWalletMatchesSigner(signer) {
  const resp = await fetch("/wallet/me");
  if (!resp.ok) {
    throw new Error("无法读取后端钱包绑定状态");
  }
  const wallet = await resp.json();
  if (!wallet.verified || !wallet.address) {
    throw new Error("请先在平台绑定并验证当前钱包，再进行 Escrow 操作");
  }
  if (wallet.address.toLowerCase() !== signer.address.toLowerCase()) {
    throw new Error(`MetaMask 当前地址与平台已验证钱包不一致。\n当前地址: ${signer.address}\n已绑定地址: ${wallet.address}`);
  }
}

// ═════════════════════════════════════════════════════════
//  1. SBT Mint / 升级
// ═════════════════════════════════════════════════════════

async function mintSBT() {
  try {
    // 先从后端获取 Merkle Proof
    const proofResp = await fetch("/api/sbt/proof");
    if (!proofResp.ok) {
      const err = await proofResp.json();
      alert(err.error || "无法获取 SBT 证明");
      return;
    }
    const proofData = await proofResp.json();

    const { signer, contracts } = await getSignerAndContracts();
    if (!contracts.sbt) {
      alert("SBT 合约未配置");
      return;
    }

    // 检查当前链上状态
    const currentSBT = await contracts.sbt.getSBT(signer.address);
    const currentTier = Number(currentSBT[1]);

    let actionLabel;
    if (currentTier === 0) {
      actionLabel = "铸造 SBT";
    } else {
      actionLabel = `升级 SBT (当前: ${TIER_NAMES[currentTier]})`;
    }

    if (!confirm(`确认${actionLabel}？\n信誉分: ${proofData.score}\nProof 节点数: ${proofData.proof.length}`)) {
      return;
    }

    const tx = await contracts.sbt.mintOrUpgradeSBT(
      proofData.score,
      proofData.proof
    );

    alert(`交易已提交！\nTx: ${tx.hash}\n等待确认...`);
    const receipt = await tx.wait();

    alert(`${actionLabel}成功！🎉\n区块: ${receipt.blockNumber}`);
    location.reload();
  } catch (err) {
    console.error("SBT mint error:", err);
    alert("SBT 操作失败: " + (err.reason || err.message));
  }
}

/**
 * 查询并显示 SBT 状态（嵌入个人主页）
 * @param {string} address - 用户钱包地址
 * @param {string} containerId - 显示容器的 DOM ID
 */
async function loadSBTStatus(address, containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;

  try {
    const cfg = await loadContractConfig();
    if (!cfg || !cfg.sbt_contract) {
      container.innerHTML = '<span class="muted">SBT 合约未配置</span>';
      return;
    }

    const provider = await getReadProvider();
    const sbt = new ethers.Contract(cfg.sbt_contract, SBT_ABI, provider);
    const data = await sbt.getSBT(address);
    const tokenId = Number(data[0]);
    const tier = Number(data[1]);
    const score = Number(data[2]);

    if (tokenId === 0) {
      container.innerHTML = '<span class="badge pending">未持有 SBT</span>';
    } else {
      container.innerHTML = `<span class="badge completed">${TIER_NAMES[tier]} (链上分: ${score})</span>`;
    }
  } catch (e) {
    console.error("Load SBT status error:", e);
    container.innerHTML = '<span class="muted">无法读取链上 SBT</span>';
  }
}

// ═════════════════════════════════════════════════════════
//  2. Escrow 资金锁定（求助者接受提议时）
// ═════════════════════════════════════════════════════════

/**
 * @param {number} taskId - HelpRequest.id
 * @param {string} helperAddress - 帮助者钱包地址
 * @param {string} amountEth - ETH 金额字符串（如 "0.01"）
 */
async function createEscrow(taskId, helperAddress, amountEth) {
  try {
    const { signer, contracts, config } = await getSignerAndContracts();
    if (!contracts.escrow) {
      alert("Escrow 合约未配置");
      return false;
    }

    const amountWei = ethers.parseEther(amountEth);
    await ensureVerifiedWalletMatchesSigner(signer);
    const tx = await contracts.escrow.createEscrow(taskId, helperAddress, { value: amountWei });

    alert(`交易已提交！\nTx: ${tx.hash}\n等待确认...`);
    try {
      const receipt = await tx.wait();
      try {
        await syncEscrowStatus(taskId, "lock", tx.hash);
      } catch (syncErr) {
        console.error("Escrow backend sync failed:", syncErr);
        alert(`链上锁仓已确认，但后端同步失败：${syncErr.message}\n请刷新页面或联系管理员处理。`);
        return false;
      }
      alert(`赏金已锁定到合约！🔒\n金额: ${amountEth} ETH\n区块: ${receipt.blockNumber}`);
    } catch (waitErr) {
      console.warn("tx.wait failed (tx may still succeed on-chain):", waitErr);
      alert(`交易已提交（Tx: ${tx.hash}），但等待确认超时。\n请刷新页面查看最新状态。`);
      return false;
    }
    return true;
  } catch (err) {
    console.error("Create escrow error:", err);
    alert("资金锁定失败: " + (err.reason || err.message));
    return false;
  }
}

// ═════════════════════════════════════════════════════════
//  3. Escrow 释放资金（求助者确认完成时）
// ═════════════════════════════════════════════════════════

async function releaseEscrow(taskId) {
  try {
    if (!confirm("确认释放赏金给帮助者？此操作不可撤销。")) return false;

    const { signer, contracts } = await getSignerAndContracts();
    if (!contracts.escrow) {
      alert("Escrow 合约未配置");
      return false;
    }

    await ensureVerifiedWalletMatchesSigner(signer);
    const tx = await contracts.escrow.releaseToHelper(taskId);

    alert(`交易已提交！\nTx: ${tx.hash}\n等待确认...`);
    try {
      await tx.wait();
      try {
        await syncEscrowStatus(taskId, "release", tx.hash);
      } catch (syncErr) {
        console.error("Escrow backend sync failed:", syncErr);
        alert(`链上释放已确认，但后端同步失败：${syncErr.message}\n请刷新页面或联系管理员处理。`);
        return false;
      }
      alert("赏金已释放！✅");
    } catch (waitErr) {
      console.warn("tx.wait failed:", waitErr);
      alert(`交易已提交（Tx: ${tx.hash}），请刷新页面查看状态。`);
      return false;
    }
    location.reload();
    return true;
  } catch (err) {
    console.error("Release escrow error:", err);
    alert("释放失败: " + (err.reason || err.message));
    return false;
  }
}

// ═════════════════════════════════════════════════════════
//  4. Escrow 发起仲裁
// ═════════════════════════════════════════════════════════

async function raiseDispute(taskId) {
  try {
    if (!confirm("确认对此任务发起仲裁？\n争议将交由金牌用户投票裁决。")) return false;

    const { signer, contracts } = await getSignerAndContracts();
    if (!contracts.escrow) {
      alert("Escrow 合约未配置");
      return false;
    }

    await ensureVerifiedWalletMatchesSigner(signer);
    const tx = await contracts.escrow.raiseDispute(taskId);

    alert(`交易已提交！\nTx: ${tx.hash}\n等待确认...`);
    try {
      await tx.wait();
      try {
        await syncEscrowStatus(taskId, "dispute", tx.hash);
      } catch (syncErr) {
        console.error("Escrow backend sync failed:", syncErr);
        alert(`链上仲裁已发起，但后端同步失败：${syncErr.message}\n请刷新页面或联系管理员处理。`);
        return false;
      }
      alert("仲裁已发起！⚖️ 等待专家用户投票。");
    } catch (waitErr) {
      console.warn("tx.wait failed:", waitErr);
      alert(`交易已提交（Tx: ${tx.hash}），请刷新页面查看状态。`);
      return false;
    }
    location.reload();
    return true;
  } catch (err) {
    console.error("Raise dispute error:", err);
    alert("发起仲裁失败: " + (err.reason || err.message));
    return false;
  }
}

// ═════════════════════════════════════════════════════════
//  5. 查询 Escrow 状态（页面加载时）
// ═════════════════════════════════════════════════════════

const ESCROW_STATUS_NAMES = ["不存在", "已锁定", "已完成", "争议中", "已裁决"];

async function getReadProvider() {
  const cfg = await loadContractConfig();
  if (cfg && cfg.rpc_url) {
    return new ethers.JsonRpcProvider(cfg.rpc_url);
  } else if (window.ethereum) {
    return new ethers.BrowserProvider(window.ethereum);
  }
  throw new Error("No provider available");
}

async function loadEscrowStatus(taskId, containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;

  try {
    const cfg = await loadContractConfig();
    if (!cfg || !cfg.escrow_contract) {
      container.innerHTML = "";
      return;
    }

    const provider = await getReadProvider();
    const escrow = new ethers.Contract(cfg.escrow_contract, ESCROW_ABI, provider);
    const data = await escrow.getEscrow(taskId);
    const status = Number(data[3]);
    const amount = data[2];

    if (status === 0) {
      container.innerHTML = '<span class="muted">链上无托管记录</span>';
    } else {
      const badgeClass = { 1: "pending", 2: "completed", 3: "rejected", 4: "completed" };
      container.innerHTML = `
        <span class="badge ${badgeClass[status] || ''}">
          ⛓️ ${ESCROW_STATUS_NAMES[status]} | ${ethers.formatEther(amount)} ETH
        </span>
      `;
    }
  } catch (e) {
    console.error("Load escrow status error:", e);
    container.innerHTML = "";
  }
}
