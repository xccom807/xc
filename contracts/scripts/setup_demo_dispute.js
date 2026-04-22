/**
 * setup_demo_dispute.js
 *
 * 用临时钱包作为 requester 创建 Escrow 争议，
 * 确保部署者地址（用户 MetaMask）不是当事人，可以作为仲裁员投票。
 *
 * Usage:
 *   npx hardhat run scripts/setup_demo_dispute.js --network sepolia
 */

const ESCROW_ADDRESS = "0x90413AfD18C53172d09caD650FB5Fd80b7154002";
const HELPER_ADDRESS = "0x90F79bf6EB2c4f870365E785982E1f101E93b906";
const TASK_ID = 77;          // 使用新的 task ID 避免与旧的冲突
const ESCROW_AMOUNT = "0.003";
const FUND_BURNER  = "0.006"; // 给临时钱包的 ETH（escrow + gas）

async function main() {
  const [deployer] = await ethers.getSigners();
  console.log("Deployer (your MetaMask):", deployer.address);

  // 1. 创建临时钱包作为 requester
  const burner = ethers.Wallet.createRandom().connect(ethers.provider);
  console.log("Burner requester:", burner.address);

  // 2. 给临时钱包转 ETH
  console.log(`\nFunding burner with ${FUND_BURNER} ETH...`);
  const fundTx = await deployer.sendTransaction({
    to: burner.address,
    value: ethers.parseEther(FUND_BURNER),
  });
  await fundTx.wait();
  console.log("  ✅ Funded");

  // 3. 临时钱包创建 Escrow
  const escrow = new ethers.Contract(
    ESCROW_ADDRESS,
    [
      "function createEscrow(uint256 taskId, address helper) external payable",
      "function raiseDispute(uint256 taskId) external",
      "function getEscrow(uint256 taskId) external view returns (address,address,uint256,uint8,uint64,uint64,uint32,uint32)",
    ],
    burner
  );

  console.log(`\nCreating escrow for task #${TASK_ID}...`);
  const tx1 = await escrow.createEscrow(TASK_ID, HELPER_ADDRESS, {
    value: ethers.parseEther(ESCROW_AMOUNT),
  });
  await tx1.wait();
  console.log("  ✅ Escrow created (Locked)");

  // 4. 临时钱包发起争议
  console.log("Raising dispute...");
  const tx2 = await escrow.raiseDispute(TASK_ID);
  await tx2.wait();
  console.log("  ✅ Dispute raised!");

  // 5. 验证
  const data = await escrow.getEscrow(TASK_ID);
  const statusNames = ["None", "Locked", "Completed", "Disputed", "Resolved"];
  console.log(`\nFinal state: ${statusNames[Number(data[3])]}`);
  console.log(`  Requester: ${data[0]}  (burner)`);
  console.log(`  Helper:    ${data[1]}`);
  console.log(`  Amount:    ${ethers.formatEther(data[2])} ETH`);
  console.log(`\n  Your MetaMask ${deployer.address} is NOT a party — can vote! ✅`);
  console.log(`\n🎉 Use task ID ${TASK_ID} in the arbitration hall.`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
