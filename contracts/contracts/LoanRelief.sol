// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

/// @title LoanRelief
/// @notice Records a farmer loan and the one relief event allowed each season.
/// @dev Integers only. Rainfall is tenths of a millimetre (1363.0 mm = 13630).
///      Rates and reductions are basis points (100% = 10000). Money is cents of a
///      demo currency (100 cents = 1.00). This contract does not read weather and
///      does not know about a model score. The oracle sends an already-decided
///      rainfall total. There is no external call, so there is no reentrancy path.
///
///      Cumulative reductions are capped at maxReductionBps for the life of the
///      loan. That running cap is an explicit RainCheck decision so a 30% term
///      cannot be posted again and again. The same running cap applies to
///      deferred months.
contract LoanRelief is Ownable {
    enum ReliefType {
        REDUCTION,
        DEFERRAL
    }

    struct Loan {
        address borrower;
        uint256 principalCents;
        uint16 annualRateBps;
        uint16 termMonths;
        uint32 triggerRainfallTenthsMm;
        uint16 maxReductionBps;
        uint16 maxDeferralMonths;
        uint256 paidCents;
        uint16 reductionBpsApplied;
        uint16 deferralMonthsApplied;
    }

    struct ReliefRecord {
        uint16 seasonId;
        ReliefType reliefType;
        uint256 reliefValue;
        uint32 observedRainfallTenthsMm;
        bytes32 dataSourceHash;
        uint64 timestamp;
    }

    address public oracle;
    uint256 public nextLoanId = 1;

    mapping(uint256 => Loan) private _loans;
    mapping(uint256 => ReliefRecord[]) private _relief;
    mapping(uint256 => mapping(uint16 => bool)) private _seasonUsed;
    mapping(uint256 => mapping(bytes32 => bool)) private _evidenceUsed;

    error NotOracle();
    error LoanNotFound();
    error ZeroAddress();
    error InvalidPrincipal();
    error InvalidTerm();
    error InvalidBps();
    error InvalidTrigger();
    error InvalidReliefValue();
    error InvalidPayment();
    error RainfallNotBelowTrigger();
    error ReductionExceedsMax();
    error TotalReductionExceedsMax();
    error DeferralExceedsMax();
    error TotalDeferralExceedsMax();
    error ReliefAlreadyAppliedForSeason();
    error DuplicateEvidence();
    error NotBorrowerOrOracle();

    event LoanCreated(
        uint256 indexed loanId,
        address indexed borrower,
        uint256 principalCents,
        uint16 annualRateBps,
        uint16 termMonths,
        uint32 triggerRainfallTenthsMm,
        uint16 maxReductionBps,
        uint16 maxDeferralMonths
    );
    event ReliefApplied(
        uint256 indexed loanId,
        uint16 seasonId,
        ReliefType reliefType,
        uint256 reliefValue,
        uint32 observedRainfallTenthsMm,
        bytes32 dataSourceHash,
        uint64 timestamp
    );
    event PaymentRecorded(uint256 indexed loanId, address indexed payer, uint256 amountCents, uint256 paidTotalCents);
    event OracleChanged(address indexed previousOracle, address indexed newOracle);

    /// @param initialOracle The only address allowed to call applyRelief. Account #1 on a local Hardhat node.
    constructor(address initialOracle) Ownable(msg.sender) {
        if (initialOracle == address(0)) revert ZeroAddress();
        oracle = initialOracle;
        emit OracleChanged(address(0), initialOracle);
    }

    /// @notice Replace the oracle. The owner cannot apply relief by doing this unless they set themselves.
    function setOracle(address newOracle) external onlyOwner {
        if (newOracle == address(0)) revert ZeroAddress();
        address previous = oracle;
        oracle = newOracle;
        emit OracleChanged(previous, newOracle);
    }

    /// @notice Store loan terms. They have no setter after this call.
    /// @return loanId The new id, starting at 1.
    function createLoan(
        address borrower,
        uint256 principalCents,
        uint16 annualRateBps,
        uint16 termMonths,
        uint32 triggerRainfallTenthsMm,
        uint16 maxReductionBps,
        uint16 maxDeferralMonths
    ) external returns (uint256 loanId) {
        if (borrower == address(0)) revert ZeroAddress();
        if (principalCents == 0) revert InvalidPrincipal();
        if (termMonths == 0 || termMonths > 600) revert InvalidTerm();
        if (annualRateBps > 10000 || maxReductionBps > 10000) revert InvalidBps();
        if (triggerRainfallTenthsMm == 0) revert InvalidTrigger();
        if (maxDeferralMonths > 600) revert InvalidTerm();

        loanId = nextLoanId++;
        _loans[loanId] = Loan({
            borrower: borrower,
            principalCents: principalCents,
            annualRateBps: annualRateBps,
            termMonths: termMonths,
            triggerRainfallTenthsMm: triggerRainfallTenthsMm,
            maxReductionBps: maxReductionBps,
            maxDeferralMonths: maxDeferralMonths,
            paidCents: 0,
            reductionBpsApplied: 0,
            deferralMonthsApplied: 0
        });
        emit LoanCreated(
            loanId,
            borrower,
            principalCents,
            annualRateBps,
            termMonths,
            triggerRainfallTenthsMm,
            maxReductionBps,
            maxDeferralMonths
        );
    }

    /// @notice Record one relief event for one season. Only the oracle can call this.
    /// @param reliefValue Basis points for REDUCTION, or months for DEFERRAL.
    /// @param dataSourceHash keccak256 of the canonical weather evidence JSON.
    /// @param seasonId The season year, for example 2017.
    function applyRelief(
        uint256 loanId,
        uint32 observedRainfallTenthsMm,
        ReliefType reliefType,
        uint256 reliefValue,
        bytes32 dataSourceHash,
        uint16 seasonId
    ) external {
        if (msg.sender != oracle) revert NotOracle();
        if (!_exists(loanId)) revert LoanNotFound();
        if (reliefValue == 0) revert InvalidReliefValue();
        if (dataSourceHash == bytes32(0)) revert InvalidReliefValue();

        Loan storage loan = _loans[loanId];
        if (observedRainfallTenthsMm >= loan.triggerRainfallTenthsMm) revert RainfallNotBelowTrigger();
        if (_seasonUsed[loanId][seasonId]) revert ReliefAlreadyAppliedForSeason();
        if (_evidenceUsed[loanId][dataSourceHash]) revert DuplicateEvidence();

        if (reliefType == ReliefType.REDUCTION) {
            if (reliefValue > 10000) revert InvalidBps();
            if (reliefValue > loan.maxReductionBps) revert ReductionExceedsMax();
            uint256 totalReduction = uint256(loan.reductionBpsApplied) + reliefValue;
            if (totalReduction > loan.maxReductionBps) revert TotalReductionExceedsMax();
            loan.reductionBpsApplied = uint16(totalReduction);
        } else if (reliefType == ReliefType.DEFERRAL) {
            if (reliefValue > loan.maxDeferralMonths) revert DeferralExceedsMax();
            uint256 totalDeferral = uint256(loan.deferralMonthsApplied) + reliefValue;
            if (totalDeferral > loan.maxDeferralMonths) revert TotalDeferralExceedsMax();
            loan.deferralMonthsApplied = uint16(totalDeferral);
        } else {
            revert InvalidReliefValue();
        }

        _seasonUsed[loanId][seasonId] = true;
        _evidenceUsed[loanId][dataSourceHash] = true;
        uint64 timestamp = uint64(block.timestamp);
        _relief[loanId].push(
            ReliefRecord({
                seasonId: seasonId,
                reliefType: reliefType,
                reliefValue: reliefValue,
                observedRainfallTenthsMm: observedRainfallTenthsMm,
                dataSourceHash: dataSourceHash,
                timestamp: timestamp
            })
        );
        emit ReliefApplied(
            loanId,
            seasonId,
            reliefType,
            reliefValue,
            observedRainfallTenthsMm,
            dataSourceHash,
            timestamp
        );
    }

    /// @notice Add a payment. The borrower or the oracle may call this.
    function recordPayment(uint256 loanId, uint256 amountCents) external {
        if (!_exists(loanId)) revert LoanNotFound();
        if (amountCents == 0) revert InvalidPayment();
        Loan storage loan = _loans[loanId];
        if (msg.sender != loan.borrower && msg.sender != oracle) revert NotBorrowerOrOracle();
        loan.paidCents += amountCents;
        emit PaymentRecorded(loanId, msg.sender, amountCents, loan.paidCents);
    }

    function getLoan(uint256 loanId) external view returns (Loan memory) {
        if (!_exists(loanId)) revert LoanNotFound();
        return _loans[loanId];
    }

    function getReliefHistory(uint256 loanId) external view returns (ReliefRecord[] memory) {
        if (!_exists(loanId)) revert LoanNotFound();
        return _relief[loanId];
    }

    function getReliefCount(uint256 loanId) external view returns (uint256) {
        if (!_exists(loanId)) revert LoanNotFound();
        return _relief[loanId].length;
    }

    function _exists(uint256 loanId) private view returns (bool) {
        return loanId != 0 && loanId < nextLoanId;
    }
}
