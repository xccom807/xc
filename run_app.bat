:: DailyHelper - Community Help Platform Launcher
:: Activates virtual environment and runs the Flask application

@echo off
title DailyHelper - Community Help Platform

:: ---- Blockchain / Web3 Configuration ----
:: 从 Infura 获取的 RPC URL（当前使用 Sepolia 测试网）
set ETH_RPC_URL=https://sepolia.infura.io/v3/78fe51a047cc4283a879c99a59cdc09e
set ETH_CHAIN_NAME=sepolia
set ETH_CHAIN_ID=11155111
:: 以太坊钱包私钥（请勿泄露！此私钥已暴露，请尽快更换！）
set ETH_SIGNER_PRIVATE_KEY=d0863861c64d330cfcc228d6dd79e51ff9d10e0728976c8472e90f2191235a0f
:: 可选：区块浏览器地址
set ETH_EXPLORER_TX_BASE_URL=https://sepolia.etherscan.io/tx
:: 是否自动上链
set BLOCKCHAIN_ANCHOR_AUTO=false
:: ---- Smart Contracts (Sepolia) ----
set SBT_CONTRACT_ADDRESS=0xC80713Ae1aB233BB29b9991a80BA7594f5C128F3
set ESCROW_CONTRACT_ADDRESS=0x90413AfD18C53172d09caD650FB5Fd80b7154002
set DAO_VOTE_THRESHOLD=1

:: Activate virtual environment and run Flask app
echo Starting DailyHelper application...
echo.
echo The app will be available at: http://127.0.0.1:5000
echo Press Ctrl+C to stop the server
echo.
call myenv\Scripts\activate.bat && python app.py

:: If the app exits, keep the window open
echo.
echo Application stopped.
pause
