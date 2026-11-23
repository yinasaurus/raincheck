import { expect } from "chai";
import { ethers } from "hardhat";
import { LoanRelief } from "../typechain-types";

const REDUCTION = 0;
const DEFERRAL = 1;

async function deploy() {
  const [owner, oracle, borrower, stranger] = await ethers.getSigners();
  const factory = await ethers.getContractFactory("LoanRelief");
  const contract = (await factory.deploy(oracle.address)) as unknown as LoanRelief;
  await contract.waitForDeployment();
  return { owner, oracle, borrower, stranger, contract };
}

async function createDefaultLoan(contract: LoanRelief, borrower: string) {
  return contract.createLoan(
    borrower,
    5_000_000n,
    1200,
    12,
    13_630,
    3000,
    2,
  );
}

describe("LoanRelief", function () {
  it("stores terms and rejects bad inputs", async function () {
    const { contract, borrower } = await deploy();
    await createDefaultLoan(contract, borrower.address);
    const loan = await contract.getLoan(1);
    expect(loan.borrower).to.equal(borrower.address);
    expect(loan.principalCents).to.equal(5_000_000n);
    expect(loan.annualRateBps).to.equal(1200);
    expect(loan.termMonths).to.equal(12);
    expect(loan.triggerRainfallTenthsMm).to.equal(13_630);
    expect(loan.maxReductionBps).to.equal(3000);
    expect(loan.maxDeferralMonths).to.equal(2);
    expect(loan.paidCents).to.equal(0n);

    await expect(contract.createLoan(ethers.ZeroAddress, 1, 0, 1, 1, 0, 0)).to.be.revertedWithCustomError(
      contract,
      "ZeroAddress",
    );
    await expect(contract.createLoan(borrower.address, 0, 0, 1, 1, 0, 0)).to.be.revertedWithCustomError(
      contract,
      "InvalidPrincipal",
    );
    await expect(contract.createLoan(borrower.address, 1, 0, 0, 1, 0, 0)).to.be.revertedWithCustomError(
      contract,
      "InvalidTerm",
    );
    await expect(contract.createLoan(borrower.address, 1, 10001, 1, 1, 0, 0)).to.be.revertedWithCustomError(
      contract,
      "InvalidBps",
    );
    await expect(contract.createLoan(borrower.address, 1, 0, 1, 1, 10001, 0)).to.be.revertedWithCustomError(
      contract,
      "InvalidBps",
    );
    await expect(contract.createLoan(borrower.address, 1, 0, 1, 0, 0, 0)).to.be.revertedWithCustomError(
      contract,
      "InvalidTrigger",
    );
    await expect(contract.getLoan(99)).to.be.revertedWithCustomError(contract, "LoanNotFound");
  });

  it("applies a reduction and a deferral and emits the recorded fields", async function () {
    const { contract, oracle, borrower } = await deploy();
    await createDefaultLoan(contract, borrower.address);
    const hash = ethers.id("evidence-2017");
    const tx = await contract
      .connect(oracle)
      .applyRelief(1, 12_439, REDUCTION, 3000, hash, 2017);
    const receipt = await tx.wait();
    const block = await ethers.provider.getBlock(receipt!.blockNumber);
    await expect(tx)
      .to.emit(contract, "ReliefApplied")
      .withArgs(1n, 2017, REDUCTION, 3000n, 12_439, hash, block!.timestamp);
    expect(await contract.getReliefCount(1)).to.equal(1n);
    const history = await contract.getReliefHistory(1);
    expect(history[0].seasonId).to.equal(2017);
    expect(history[0].reliefType).to.equal(REDUCTION);
    expect(history[0].reliefValue).to.equal(3000n);
    expect(history[0].observedRainfallTenthsMm).to.equal(12_439);
    expect(history[0].dataSourceHash).to.equal(hash);
    const after = await contract.getLoan(1);
    expect(after.maxReductionBps).to.equal(3000);
    expect(after.reductionBpsApplied).to.equal(3000);

    await createDefaultLoan(contract, borrower.address);
    const deferral = await contract
      .connect(oracle)
      .applyRelief(2, 10_000, DEFERRAL, 2, ethers.id("evidence-2004"), 2004);
    await expect(deferral).to.emit(contract, "ReliefApplied");
    expect((await contract.getLoan(2)).deferralMonthsApplied).to.equal(2);
  });

  it("rejects anyone except the oracle", async function () {
    const { contract, borrower, stranger } = await deploy();
    await createDefaultLoan(contract, borrower.address);
    await expect(
      contract.connect(stranger).applyRelief(1, 1, REDUCTION, 100, ethers.id("x"), 2017),
    ).to.be.revertedWithCustomError(contract, "NotOracle");
    await expect(
      contract.connect(borrower).applyRelief(1, 1, REDUCTION, 100, ethers.id("x"), 2017),
    ).to.be.revertedWithCustomError(contract, "NotOracle");
  });

  it("rejects rainfall that is not strictly below the trigger", async function () {
    const { contract, oracle, borrower } = await deploy();
    await createDefaultLoan(contract, borrower.address);
    await expect(
      contract.connect(oracle).applyRelief(1, 13_630, REDUCTION, 100, ethers.id("eq"), 2017),
    ).to.be.revertedWithCustomError(contract, "RainfallNotBelowTrigger");
    await expect(
      contract.connect(oracle).applyRelief(1, 13_631, REDUCTION, 100, ethers.id("above"), 2017),
    ).to.be.revertedWithCustomError(contract, "RainfallNotBelowTrigger");
  });

  it("enforces per-call and cumulative caps for both relief types", async function () {
    const { contract, oracle, borrower } = await deploy();
    await createDefaultLoan(contract, borrower.address);
    await expect(
      contract.connect(oracle).applyRelief(1, 1, REDUCTION, 3001, ethers.id("too-big"), 2017),
    ).to.be.revertedWithCustomError(contract, "ReductionExceedsMax");

    await contract.connect(oracle).applyRelief(1, 1, REDUCTION, 2000, ethers.id("first"), 2016);
    await expect(
      contract.connect(oracle).applyRelief(1, 1, REDUCTION, 2000, ethers.id("second"), 2015),
    ).to.be.revertedWithCustomError(contract, "TotalReductionExceedsMax");

    await createDefaultLoan(contract, borrower.address);
    await expect(
      contract.connect(oracle).applyRelief(2, 1, DEFERRAL, 3, ethers.id("defer-big"), 2017),
    ).to.be.revertedWithCustomError(contract, "DeferralExceedsMax");
    await contract.connect(oracle).applyRelief(2, 1, DEFERRAL, 1, ethers.id("defer-1"), 2014);
    await expect(
      contract.connect(oracle).applyRelief(2, 1, DEFERRAL, 2, ethers.id("defer-2"), 2013),
    ).to.be.revertedWithCustomError(contract, "TotalDeferralExceedsMax");
  });

  it("allows one relief per season and rejects a repeated evidence hash", async function () {
    const { contract, oracle, borrower } = await deploy();
    await createDefaultLoan(contract, borrower.address);
    const hash = ethers.id("same-payload");
    await contract.connect(oracle).applyRelief(1, 100, REDUCTION, 1000, hash, 2017);
    await expect(
      contract.connect(oracle).applyRelief(1, 100, DEFERRAL, 1, ethers.id("other-payload"), 2017),
    ).to.be.revertedWithCustomError(contract, "ReliefAlreadyAppliedForSeason");
    await expect(
      contract.connect(oracle).applyRelief(1, 100, REDUCTION, 1000, hash, 2018),
    ).to.be.revertedWithCustomError(contract, "DuplicateEvidence");
  });

  it("records a payment from the borrower or the oracle, and rejects anyone else", async function () {
    const { contract, oracle, borrower, stranger } = await deploy();
    await createDefaultLoan(contract, borrower.address);
    const paid = await contract.connect(borrower).recordPayment(1, 10_000);
    await expect(paid)
      .to.emit(contract, "PaymentRecorded")
      .withArgs(1n, borrower.address, 10_000n, 10_000n);
    await contract.connect(oracle).recordPayment(1, 5_000);
    expect((await contract.getLoan(1)).paidCents).to.equal(15_000n);
    await expect(contract.connect(stranger).recordPayment(1, 1)).to.be.revertedWithCustomError(
      contract,
      "NotBorrowerOrOracle",
    );
    await expect(contract.connect(borrower).recordPayment(1, 0)).to.be.revertedWithCustomError(
      contract,
      "InvalidPayment",
    );
  });

  it("lets only the owner change the oracle", async function () {
    const { contract, owner, oracle, stranger } = await deploy();
    await expect(contract.connect(oracle).setOracle(stranger.address)).to.be.revertedWithCustomError(
      contract,
      "OwnableUnauthorizedAccount",
    );
    await expect(contract.connect(owner).setOracle(ethers.ZeroAddress)).to.be.revertedWithCustomError(
      contract,
      "ZeroAddress",
    );
    await expect(contract.connect(owner).setOracle(stranger.address))
      .to.emit(contract, "OracleChanged")
      .withArgs(oracle.address, stranger.address);
    expect(await contract.oracle()).to.equal(stranger.address);
  });

  it("emits LoanCreated with the terms that were stored", async function () {
    const { contract, borrower } = await deploy();
    const tx = await createDefaultLoan(contract, borrower.address);
    await expect(tx)
      .to.emit(contract, "LoanCreated")
      .withArgs(1n, borrower.address, 5_000_000n, 1200, 12, 13_630, 3000, 2);
  });
});
