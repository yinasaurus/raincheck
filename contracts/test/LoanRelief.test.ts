import { expect } from "chai";
import { ethers } from "hardhat";
import { loadFixture, time } from "@nomicfoundation/hardhat-network-helpers";

// Units: rainfall = tenths of mm, percentages = basis points, money = cents.
const TRIGGER = 13630; // 1,363.0 mm
const PRINCIPAL = 100_000_00n; // 100,000.00
const REDUCTION = 0, DEFERRAL = 1;
const hash = (s: string) => ethers.keccak256(ethers.toUtf8Bytes(s));

async function deployFixture() {
  const [owner, oracle, borrower, stranger, other] = await ethers.getSigners();
  const Factory = await ethers.getContractFactory("LoanRelief");
  const c = await Factory.deploy(oracle.address);
  await c.waitForDeployment();
  return { c, owner, oracle, borrower, stranger, other };
}

async function loanFixture() {
  const base = await deployFixture();
  // 12% APR, 24 months, trigger 1363.0mm, max reduction 50%, max deferral 4 months
  await base.c.createLoan(base.borrower.address, PRINCIPAL, 1200, 24, TRIGGER, 5000, 4);
  return base;
}

describe("LoanRelief", () => {
  describe("deployment and admin", () => {
    it("sets owner and oracle", async () => {
      const { c, owner, oracle } = await loadFixture(deployFixture);
      expect(await c.owner()).to.equal(owner.address);
      expect(await c.oracle()).to.equal(oracle.address);
    });
    it("rejects a zero oracle address at deploy", async () => {
      const F = await ethers.getContractFactory("LoanRelief");
      await expect(F.deploy(ethers.ZeroAddress)).to.be.revertedWithCustomError(F, "InvalidInput");
    });
    it("only the owner can change the oracle", async () => {
      const { c, oracle, stranger, other } = await loadFixture(deployFixture);
      await expect(c.connect(stranger).setOracle(other.address)).to.be.revertedWithCustomError(c, "NotOwner");
      await expect(c.connect(oracle).setOracle(other.address)).to.be.revertedWithCustomError(c, "NotOwner");
      await expect(c.setOracle(other.address)).to.emit(c, "OracleChanged").withArgs(oracle.address, other.address);
      expect(await c.oracle()).to.equal(other.address);
    });
    it("rejects setting a zero oracle", async () => {
      const { c } = await loadFixture(deployFixture);
      await expect(c.setOracle(ethers.ZeroAddress)).to.be.revertedWithCustomError(c, "InvalidInput");
    });
  });

  describe("createLoan", () => {
    it("stores terms and emits LoanCreated", async () => {
      const { c, borrower } = await loadFixture(deployFixture);
      await expect(c.createLoan(borrower.address, PRINCIPAL, 1200, 24, TRIGGER, 5000, 4))
        .to.emit(c, "LoanCreated")
        .withArgs(1, borrower.address, PRINCIPAL, 1200, 24, TRIGGER, 5000, 4);
      const loan = await c.getLoan(1);
      expect(loan.borrower).to.equal(borrower.address);
      expect(loan.principalCents).to.equal(PRINCIPAL);
      expect(loan.triggerRainfallTenthsMm).to.equal(TRIGGER);
      expect(loan.reductionUsedBps).to.equal(0);
      expect(loan.deferralUsedMonths).to.equal(0);
      expect(await c.loanCount()).to.equal(1);
    });
    it("assigns incrementing ids", async () => {
      const { c, borrower } = await loadFixture(deployFixture);
      await c.createLoan(borrower.address, PRINCIPAL, 1200, 24, TRIGGER, 5000, 4);
      await c.createLoan(borrower.address, PRINCIPAL, 1200, 24, TRIGGER, 5000, 4);
      expect(await c.loanCount()).to.equal(2);
    });
    const bad: [string, (b: string) => any[]][] = [
      ["zero borrower", () => [ethers.ZeroAddress, PRINCIPAL, 1200, 24, TRIGGER, 5000, 4]],
      ["zero principal", (b) => [b, 0, 1200, 24, TRIGGER, 5000, 4]],
      ["zero term", (b) => [b, PRINCIPAL, 1200, 0, TRIGGER, 5000, 4]],
      ["rate over 100%", (b) => [b, PRINCIPAL, 10001, 24, TRIGGER, 5000, 4]],
      ["zero trigger", (b) => [b, PRINCIPAL, 1200, 24, 0, 5000, 4]],
      ["max reduction over 100%", (b) => [b, PRINCIPAL, 1200, 24, TRIGGER, 10001, 4]],
      ["max deferral longer than term", (b) => [b, PRINCIPAL, 1200, 24, TRIGGER, 5000, 25]],
    ];
    for (const [name, args] of bad) {
      it(`reverts on ${name}`, async () => {
        const { c, borrower } = await loadFixture(deployFixture);
        await expect((c as any).createLoan(...args(borrower.address))).to.be.revertedWithCustomError(c, "InvalidInput");
      });
    }
    it("reverts reading a missing loan", async () => {
      const { c } = await loadFixture(deployFixture);
      await expect(c.getLoan(99)).to.be.revertedWithCustomError(c, "LoanNotFound");
      await expect(c.getReliefHistory(99)).to.be.revertedWithCustomError(c, "LoanNotFound");
    });
  });

  describe("applyRelief: success paths", () => {
    it("applies a reduction and records full history + event", async () => {
      const { c, oracle } = await loadFixture(loanFixture);
      const h = hash("evidence-2004");
      await expect(c.connect(oracle).applyRelief(1, 2004, 12440, REDUCTION, 3000, h))
        .to.emit(c, "ReliefApplied")
        .withArgs(1, 2004, REDUCTION, 3000, 12440, h, (ts: bigint) => ts > 0n);
      const loan = await c.getLoan(1);
      expect(loan.reductionUsedBps).to.equal(3000);
      expect(await c.getReliefCount(1)).to.equal(1);
      const hist = await c.getReliefHistory(1);
      expect(hist[0].seasonId).to.equal(2004);
      expect(hist[0].reliefType).to.equal(REDUCTION);
      expect(hist[0].reliefValue).to.equal(3000);
      expect(hist[0].observedRainfallTenthsMm).to.equal(12440);
      expect(hist[0].dataSourceHash).to.equal(h);
      expect(await c.seasonRelieved(1, 2004)).to.equal(true);
    });
    it("applies a deferral", async () => {
      const { c, oracle } = await loadFixture(loanFixture);
      await c.connect(oracle).applyRelief(1, 2017, 12390, DEFERRAL, 2, hash("e2017"));
      const loan = await c.getLoan(1);
      expect(loan.deferralUsedMonths).to.equal(2);
      expect(loan.reductionUsedBps).to.equal(0);
    });
    it("allows relief in different seasons up to the cumulative cap", async () => {
      const { c, oracle } = await loadFixture(loanFixture);
      await c.connect(oracle).applyRelief(1, 2003, 12350, REDUCTION, 3000, hash("a"));
      await c.connect(oracle).applyRelief(1, 2004, 12440, REDUCTION, 2000, hash("b")); // total 5000 == cap
      expect((await c.getLoan(1)).reductionUsedBps).to.equal(5000);
      expect(await c.getReliefCount(1)).to.equal(2);
    });
    it("stamps the block timestamp", async () => {
      const { c, oracle } = await loadFixture(loanFixture);
      await c.connect(oracle).applyRelief(1, 2004, 12440, REDUCTION, 1000, hash("t"));
      const hist = await c.getReliefHistory(1);
      expect(hist[0].timestamp).to.equal(await time.latest());
    });
  });

  describe("applyRelief: reverts", () => {
    it("non-oracle caller (stranger, borrower, owner)", async () => {
      const { c, stranger, borrower, owner } = await loadFixture(loanFixture);
      for (const s of [stranger, borrower, owner]) {
        await expect(c.connect(s).applyRelief(1, 2004, 12440, REDUCTION, 1000, hash("x")))
          .to.be.revertedWithCustomError(c, "NotOracle");
      }
    });
    it("unknown loan", async () => {
      const { c, oracle } = await loadFixture(loanFixture);
      await expect(c.connect(oracle).applyRelief(42, 2004, 12440, REDUCTION, 1000, hash("x")))
        .to.be.revertedWithCustomError(c, "LoanNotFound");
    });
    it("rainfall exactly equal to trigger (strictly-below rule)", async () => {
      const { c, oracle } = await loadFixture(loanFixture);
      await expect(c.connect(oracle).applyRelief(1, 2005, TRIGGER, REDUCTION, 1000, hash("x")))
        .to.be.revertedWithCustomError(c, "TriggerNotMet").withArgs(TRIGGER, TRIGGER);
    });
    it("rainfall above trigger", async () => {
      const { c, oracle } = await loadFixture(loanFixture);
      await expect(c.connect(oracle).applyRelief(1, 2005, TRIGGER + 500, REDUCTION, 1000, hash("x")))
        .to.be.revertedWithCustomError(c, "TriggerNotMet");
    });
    it("rainfall one tenth below trigger succeeds (boundary)", async () => {
      const { c, oracle } = await loadFixture(loanFixture);
      await expect(c.connect(oracle).applyRelief(1, 2005, TRIGGER - 1, REDUCTION, 1000, hash("x"))).to.not.be.reverted;
    });
    it("single reduction over the cap", async () => {
      const { c, oracle } = await loadFixture(loanFixture);
      await expect(c.connect(oracle).applyRelief(1, 2004, 12440, REDUCTION, 5001, hash("x")))
        .to.be.revertedWithCustomError(c, "ReductionCapExceeded");
    });
    it("cumulative reduction over the cap", async () => {
      const { c, oracle } = await loadFixture(loanFixture);
      await c.connect(oracle).applyRelief(1, 2003, 12350, REDUCTION, 3000, hash("a"));
      await expect(c.connect(oracle).applyRelief(1, 2004, 12440, REDUCTION, 2001, hash("b")))
        .to.be.revertedWithCustomError(c, "ReductionCapExceeded");
    });
    it("single deferral over the cap", async () => {
      const { c, oracle } = await loadFixture(loanFixture);
      await expect(c.connect(oracle).applyRelief(1, 2004, 12440, DEFERRAL, 5, hash("x")))
        .to.be.revertedWithCustomError(c, "DeferralCapExceeded");
    });
    it("cumulative deferral over the cap", async () => {
      const { c, oracle } = await loadFixture(loanFixture);
      await c.connect(oracle).applyRelief(1, 2003, 12350, DEFERRAL, 3, hash("a"));
      await expect(c.connect(oracle).applyRelief(1, 2004, 12440, DEFERRAL, 2, hash("b")))
        .to.be.revertedWithCustomError(c, "DeferralCapExceeded");
    });
    it("second relief in the same season, even with fresh evidence", async () => {
      const { c, oracle } = await loadFixture(loanFixture);
      await c.connect(oracle).applyRelief(1, 2004, 12440, REDUCTION, 1000, hash("a"));
      await expect(c.connect(oracle).applyRelief(1, 2004, 12440, DEFERRAL, 1, hash("b")))
        .to.be.revertedWithCustomError(c, "SeasonAlreadyRelieved");
    });
    it("exact-repeat evidence hash in a different season", async () => {
      const { c, oracle } = await loadFixture(loanFixture);
      await c.connect(oracle).applyRelief(1, 2003, 12350, REDUCTION, 1000, hash("same"));
      await expect(c.connect(oracle).applyRelief(1, 2004, 12440, REDUCTION, 1000, hash("same")))
        .to.be.revertedWithCustomError(c, "EvidenceAlreadyUsed");
    });
    it("zero relief value and zero evidence hash", async () => {
      const { c, oracle } = await loadFixture(loanFixture);
      await expect(c.connect(oracle).applyRelief(1, 2004, 12440, REDUCTION, 0, hash("x")))
        .to.be.revertedWithCustomError(c, "InvalidInput");
      await expect(c.connect(oracle).applyRelief(1, 2004, 12440, REDUCTION, 1000, ethers.ZeroHash))
        .to.be.revertedWithCustomError(c, "InvalidInput");
    });
    it("a failed call leaves no state behind", async () => {
      const { c, oracle } = await loadFixture(loanFixture);
      await expect(c.connect(oracle).applyRelief(1, 2005, TRIGGER + 1, REDUCTION, 1000, hash("x"))).to.be.reverted;
      expect(await c.getReliefCount(1)).to.equal(0);
      expect(await c.seasonRelieved(1, 2005)).to.equal(false);
      // and the same evidence can still be used once the rule is actually met
      await expect(c.connect(oracle).applyRelief(1, 2005, TRIGGER - 10, REDUCTION, 1000, hash("x"))).to.not.be.reverted;
    });
    it("relief on one loan does not consume caps or seasons of another loan", async () => {
      const { c, oracle, borrower } = await loadFixture(loanFixture);
      await c.createLoan(borrower.address, PRINCIPAL, 1200, 24, TRIGGER, 5000, 4);
      await c.connect(oracle).applyRelief(1, 2004, 12440, REDUCTION, 5000, hash("same"));
      await expect(c.connect(oracle).applyRelief(2, 2004, 12440, REDUCTION, 5000, hash("same"))).to.not.be.reverted;
    });
  });

  describe("oracle rotation", () => {
    it("old oracle loses access, new oracle gains it", async () => {
      const { c, oracle, other } = await loadFixture(loanFixture);
      await c.setOracle(other.address);
      await expect(c.connect(oracle).applyRelief(1, 2004, 12440, REDUCTION, 1000, hash("x")))
        .to.be.revertedWithCustomError(c, "NotOracle");
      await expect(c.connect(other).applyRelief(1, 2004, 12440, REDUCTION, 1000, hash("x"))).to.not.be.reverted;
    });
  });

  describe("recordPayment", () => {
    it("borrower can record and totals accumulate", async () => {
      const { c, borrower } = await loadFixture(loanFixture);
      await expect(c.connect(borrower).recordPayment(1, 500_00n))
        .to.emit(c, "PaymentRecorded").withArgs(1, borrower.address, 500_00n, 500_00n);
      await c.connect(borrower).recordPayment(1, 250_00n);
      expect((await c.getLoan(1)).paidCents).to.equal(750_00n);
    });
    it("oracle can record", async () => {
      const { c, oracle } = await loadFixture(loanFixture);
      await expect(c.connect(oracle).recordPayment(1, 100_00n)).to.emit(c, "PaymentRecorded");
    });
    it("stranger cannot record", async () => {
      const { c, stranger } = await loadFixture(loanFixture);
      await expect(c.connect(stranger).recordPayment(1, 100_00n)).to.be.revertedWithCustomError(c, "NotAuthorized");
    });
    it("zero amount and unknown loan revert", async () => {
      const { c, borrower } = await loadFixture(loanFixture);
      await expect(c.connect(borrower).recordPayment(1, 0)).to.be.revertedWithCustomError(c, "InvalidInput");
      await expect(c.connect(borrower).recordPayment(9, 1)).to.be.revertedWithCustomError(c, "LoanNotFound");
    });
  });
});
