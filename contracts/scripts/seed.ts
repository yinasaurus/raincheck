import fs from "fs";
import path from "path";
import { ethers } from "hardhat";

/// Optional demo loan. 50,000.00 demo currency, 12% , 12 months, trigger 1363.0 mm.
async function main() {
  const deploymentPath = path.resolve(__dirname, "../../backend/chain/deployment.json");
  const deployment = JSON.parse(fs.readFileSync(deploymentPath, "utf8"));
  const signers = await ethers.getSigners();
  const borrower = signers[2];
  const contract = await ethers.getContractAt("LoanRelief", deployment.address);
  const tx = await contract.createLoan(
    borrower.address,
    5_000_000n,
    1200,
    12,
    13_630,
    3000,
    2,
  );
  const receipt = await tx.wait();
  const created = receipt?.logs
    .map((log) => {
      try {
        return contract.interface.parseLog(log);
      } catch {
        return null;
      }
    })
    .find((parsed) => parsed?.name === "LoanCreated");
  console.log(`Seeded loan ${created?.args.loanId.toString()} for ${borrower.address}`);
  console.log(`Transaction ${receipt?.hash}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
