require("@nomicfoundation/hardhat-toolbox");

const PRIVATE_KEY = process.env.ETH_SIGNER_PRIVATE_KEY || "d0863861c64d330cfcc228d6dd79e51ff9d10e0728976c8472e90f2191235a0f";

/** @type import('hardhat/config').HardhatUserConfig */
module.exports = {
  solidity: {
    version: "0.8.24",
    settings: {
      evmVersion: "cancun",
      optimizer: {
        enabled: true,
        runs: 200,
      },
    },
  },
  paths: {
    sources: "./src",
    cache: "./cache",
    artifacts: "./artifacts",
  },
  networks: {
    sepolia: {
      url: process.env.ETH_RPC_URL || "https://sepolia.infura.io/v3/78fe51a047cc4283a879c99a59cdc09e",
      accounts: [`0x${PRIVATE_KEY}`],
    },
  },
};
