// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title LoanRelief
/// @notice Records weather-adaptive loan terms and enforces hard limits on relief.
/// @dev The contract does NOT fetch or verify weather data. A trusted oracle submits the
///      observed season rainfall plus a hash of the evidence payload. The contract only
///      (1) checks the trigger rule, (2) enforces caps, and (3) writes an auditable history.
///      Units: rainfall in tenths of a millimetre, percentages in basis points (10000 = 100%),
///      money in cents.
contract LoanRelief {
    // ---------------------------------------------------------------- types
    enum ReliefType {
        REDUCTION, // reliefValue = reduction in basis points
        DEFERRAL // reliefValue = number of months deferred
    }

    struct Loan {
        address borrower;
        uint256 principalCents;
        uint16 annualRateBps;
        uint16 termMonths;
        uint32 triggerRainfallTenthsMm; // relief only if observed rainfall is strictly below this
        uint16 maxReductionBps; // cumulative cap across all relief events
        uint16 maxDeferralMonths; // cumulative cap across all relief events
        uint16 reductionUsedBps;
        uint16 deferralUsedMonths;
        uint256 paidCents;
        bool exists;
    }

    struct ReliefEvent {
        uint16 seasonId;
        ReliefType reliefType;
        uint32 reliefValue;
        uint32 observedRainfallTenthsMm;
        bytes32 dataSourceHash;
        uint64 timestamp;
    }

    // -------------------------------------------------------------- storage
    address public owner;
    address public oracle;
    uint256 public loanCount;

    mapping(uint256 => Loan) private _loans;
    mapping(uint256 => ReliefEvent[]) private _history;
    mapping(uint256 => mapping(uint16 => bool)) private _seasonRelieved;
    mapping(uint256 => mapping(bytes32 => bool)) private _evidenceUsed;

    // --------------------------------------------------------------- events
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
        uint16 indexed seasonId,
        ReliefType reliefType,
        uint32 reliefValue,
        uint32 observedRainfallTenthsMm,
        bytes32 dataSourceHash,
        uint64 timestamp
    );
    event PaymentRecorded(uint256 indexed loanId, address indexed by, uint256 amountCents, uint256 totalPaidCents);
    event OracleChanged(address indexed previousOracle, address indexed newOracle);

    // --------------------------------------------------------------- errors
    error NotOwner();
    error NotOracle();
    error NotAuthorized();
    error LoanNotFound();
    error InvalidInput();
    error TriggerNotMet(uint32 observed, uint32 trigger);
    error ReductionCapExceeded();
    error DeferralCapExceeded();
    error SeasonAlreadyRelieved();
    error EvidenceAlreadyUsed();

    // ------------------------------------------------------------ modifiers
    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    modifier onlyOracle() {
        if (msg.sender != oracle) revert NotOracle();
        _;
    }

    constructor(address initialOracle) {
        if (initialOracle == address(0)) revert InvalidInput();
        owner = msg.sender;
        oracle = initialOracle;
        emit OracleChanged(address(0), initialOracle);
    }

    // ---------------------------------------------------------------- admin
    function setOracle(address newOracle) external onlyOwner {
        if (newOracle == address(0)) revert InvalidInput();
        emit OracleChanged(oracle, newOracle);
        oracle = newOracle;
    }

    // ---------------------------------------------------------------- loans
    /// @notice Create a loan. Terms are immutable afterwards; only relief counters and payments change.
    function createLoan(
        address borrower,
        uint256 principalCents,
        uint16 annualRateBps,
        uint16 termMonths,
        uint32 triggerRainfallTenthsMm,
        uint16 maxReductionBps,
        uint16 maxDeferralMonths
    ) external returns (uint256 loanId) {
        if (
            borrower == address(0) ||
            principalCents == 0 ||
            termMonths == 0 ||
            annualRateBps > 10_000 ||
            triggerRainfallTenthsMm == 0 ||
            maxReductionBps > 10_000 ||
            maxDeferralMonths > termMonths
        ) revert InvalidInput();

        loanId = ++loanCount;
        _loans[loanId] = Loan({
            borrower: borrower,
            principalCents: principalCents,
            annualRateBps: annualRateBps,
            termMonths: termMonths,
            triggerRainfallTenthsMm: triggerRainfallTenthsMm,
            maxReductionBps: maxReductionBps,
            maxDeferralMonths: maxDeferralMonths,
            reductionUsedBps: 0,
            deferralUsedMonths: 0,
            paidCents: 0,
            exists: true
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

    /// @notice Apply relief for one season. Oracle only.
    /// @dev Reverts unless observed rainfall is STRICTLY below the loan's trigger and every cap holds.
    ///      Design decision: reductions are capped CUMULATIVELY (not just per call), and each loan
    ///      can receive at most one relief event per season id.
    function applyRelief(
        uint256 loanId,
        uint16 seasonId,
        uint32 observedRainfallTenthsMm,
        ReliefType reliefType,
        uint32 reliefValue,
        bytes32 dataSourceHash
    ) external onlyOracle {
        Loan storage loan = _loans[loanId];
        if (!loan.exists) revert LoanNotFound();
        if (reliefValue == 0 || dataSourceHash == bytes32(0)) revert InvalidInput();
        if (observedRainfallTenthsMm >= loan.triggerRainfallTenthsMm) {
            revert TriggerNotMet(observedRainfallTenthsMm, loan.triggerRainfallTenthsMm);
        }
        if (_seasonRelieved[loanId][seasonId]) revert SeasonAlreadyRelieved();
        if (_evidenceUsed[loanId][dataSourceHash]) revert EvidenceAlreadyUsed();

        if (reliefType == ReliefType.REDUCTION) {
            uint256 newTotal = uint256(loan.reductionUsedBps) + reliefValue;
            if (newTotal > loan.maxReductionBps) revert ReductionCapExceeded();
            loan.reductionUsedBps = uint16(newTotal);
        } else {
            uint256 newTotal = uint256(loan.deferralUsedMonths) + reliefValue;
            if (newTotal > loan.maxDeferralMonths) revert DeferralCapExceeded();
            loan.deferralUsedMonths = uint16(newTotal);
        }

        _seasonRelieved[loanId][seasonId] = true;
        _evidenceUsed[loanId][dataSourceHash] = true;
        uint64 ts = uint64(block.timestamp);
        _history[loanId].push(
            ReliefEvent(seasonId, reliefType, reliefValue, observedRainfallTenthsMm, dataSourceHash, ts)
        );

        emit ReliefApplied(
            loanId,
            seasonId,
            reliefType,
            reliefValue,
            observedRainfallTenthsMm,
            dataSourceHash,
            ts
        );
    }

    /// @notice Record a repayment. Callable by the borrower or the oracle (e.g. a lender's system).
    function recordPayment(uint256 loanId, uint256 amountCents) external {
        Loan storage loan = _loans[loanId];
        if (!loan.exists) revert LoanNotFound();
        if (msg.sender != loan.borrower && msg.sender != oracle) revert NotAuthorized();
        if (amountCents == 0) revert InvalidInput();
        loan.paidCents += amountCents;
        emit PaymentRecorded(loanId, msg.sender, amountCents, loan.paidCents);
    }

    // ---------------------------------------------------------------- views
    function getLoan(uint256 loanId) external view returns (Loan memory) {
        if (!_loans[loanId].exists) revert LoanNotFound();
        return _loans[loanId];
    }

    function getReliefHistory(uint256 loanId) external view returns (ReliefEvent[] memory) {
        if (!_loans[loanId].exists) revert LoanNotFound();
        return _history[loanId];
    }

    function getReliefCount(uint256 loanId) external view returns (uint256) {
        if (!_loans[loanId].exists) revert LoanNotFound();
        return _history[loanId].length;
    }

    function seasonRelieved(uint256 loanId, uint16 seasonId) external view returns (bool) {
        return _seasonRelieved[loanId][seasonId];
    }
}
