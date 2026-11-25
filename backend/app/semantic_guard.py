"""Reject explanations that are numerically grounded and still false.

The number check only looks for digits. These rules exist because a live
answer can quote real facts and still describe the wrong mechanism.
"""

from __future__ import annotations

import re

_FEWER = re.compile(
    r"\b("
    r"fewer payments|fewer installments|less payments|less installments|"
    r"pay fewer|"
    r"payment count (?:is |was |were |has been |gets )?(?:reduced|lower|cut|decreased|smaller)|"
    r"(?:number|count) of (?:payments|installments) (?:is |was |were |has been |gets )?(?:reduced|lowered|cut|decreased|smaller)"
    r")\b",
    re.IGNORECASE,
)
_RELIEF_BECAUSE_OTHER = re.compile(
    r"\brelief\b.{0,40}\b(?:because|since)\b.{0,80}\b(?:week|date|chance|probability|estimate|request|eligib)",
    re.IGNORECASE | re.DOTALL,
)
_PAST_WEEK_CAUSE = re.compile(
    r"\brelief\b.{0,40}\b(?:because|since)\b.{0,60}\bpast week\b",
    re.IGNORECASE | re.DOTALL,
)
_TRIGGERED = re.compile(
    r"\b(?:week|date|chance|probability|estimate|request|eligibility)\b.{0,40}\b(?:caused|triggered)\b.{0,30}\brelief\b",
    re.IGNORECASE | re.DOTALL,
)
_CAUSED_BY = re.compile(
    r"\brelief\b.{0,40}\b(?:caused|triggered) by\b.{0,40}\b(?:week|date|chance|probability|estimate|request|eligibility)\b",
    re.IGNORECASE | re.DOTALL,
)
_PROMISE = re.compile(
    r"\b(?:cancelled|canceled|forgiven|waived|erased|erase|interest-free|guaranteed|guarantee|promise|will receive|you qualify|you save)\b",
    re.IGNORECASE,
)
_ADVICE = re.compile(r"\b(?:you should|i recommend|i suggest)\b", re.IGNORECASE)
_PREDICT = re.compile(
    r"\b(?:will get relief|you will get|i predict|rainfall will|the rain will)\b",
    re.IGNORECASE,
)
_NEXT = re.compile(r"\bnext (?:year|season)\b", re.IGNORECASE)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _negated(text: str, start: int, gap: int = 8) -> bool:
    prefix = text[max(0, start - 48) : start]
    return (
        re.search(
            rf"\b(?:not|no|never|without|cannot|can't)\b[\s\w,'’]{{0,{gap}}}$",
            prefix,
            re.IGNORECASE,
        )
        is not None
    )


def _fact(facts: list[dict], label: str) -> str:
    for item in facts:
        if item["label"] == label:
            return str(item["value"])
    return ""


def _has_fact_number(answer: str, value: str) -> bool:
    numbers = _NUMBER.findall(value.replace(",", ""))
    if not numbers:
        return value.lower() in answer.lower()
    normalized = answer.replace(",", "")
    return all(number in normalized for number in numbers)


def claims_fewer_payments(answer: str) -> bool:
    """Relief lowers the next payments. It does not shorten the loan."""
    for match in _FEWER.finditer(answer or ""):
        if not _negated(answer, match.start(), gap=12):
            return True
    return False


def blames_relief_on_something_other_than_final_rainfall(answer: str) -> bool:
    """Relief fires only when the final observed total is strictly below the line."""
    text = answer or ""
    for pattern in (_RELIEF_BECAUSE_OTHER, _PAST_WEEK_CAUSE, _TRIGGERED, _CAUSED_BY):
        for match in pattern.finditer(text):
            if not _negated(text, match.start(), gap=12):
                return True
    return False


def makes_a_forbidden_promise(answer: str) -> bool:
    """The page can describe the rule. It cannot cancel debt, promise money, or say the farmer qualifies."""
    for match in _PROMISE.finditer(answer or ""):
        if not _negated(answer, match.start()):
            return True
    return False


def gives_advice(answer: str) -> bool:
    """The assistant explains the page. It does not tell the farmer what to do."""
    return _ADVICE.search(answer or "") is not None


def _refusal_sentence(text: str, start: int) -> bool:
    left = max(text.rfind(".", 0, start), text.rfind("!", 0, start), text.rfind("?", 0, start))
    sentence = text[left + 1 : start]
    return re.search(r"\b(?:cannot|can't)\b", sentence, re.IGNORECASE) is not None


def predicts_beyond_the_given_chance(answer: str) -> bool:
    """The only probability on the page is this season's chance. A later season is not a forecast."""
    text = answer or ""
    for match in _PREDICT.finditer(text):
        if not _refusal_sentence(text, match.start()):
            return True
    for match in _NEXT.finditer(text):
        if _negated(text, match.start(), gap=16) or _refusal_sentence(text, match.start()):
            continue
        return True
    return False


def claims_a_cut_when_this_season_has_no_relief(answer: str, facts: list[dict]) -> bool:
    """A season above the line does not get the 30 percent cut on the next 3 payments."""
    if _fact(facts, "Relief status").startswith("Relief applied"):
        return False
    text = answer or ""
    if not (re.search(r"next 3 payments", text, re.IGNORECASE) and re.search(r"30\s*%", text)):
        return False
    if re.search(r"\b(no relief|did not|was not|not applied)\b", text, re.IGNORECASE):
        return False
    return True


def below_result_stated(answer: str, below: str) -> bool:
    """The strictly-below result is present, and it matches the fact."""
    text = answer or ""
    token = below.strip().lower()
    if token == "yes":
        if re.search(r"not strictly below", text, re.IGNORECASE):
            return False
        return re.search(r"strictly below", text, re.IGNORECASE) is not None
    if token == "no":
        return (
            re.search(
                r"strictly below the line(?::| is) no|not strictly below|above the (payment )?line",
                text,
                re.IGNORECASE,
            )
            is not None
        )
    return "not finished" in text.lower()


def why_fact_sentences(answer: str, facts: list[dict]) -> list[str]:
    """Verified lines for a why answer that already passed the deny rules and left out a figure."""
    lines: list[str] = []
    total = _fact(facts, "Season total")
    line = _fact(facts, "Payment line")
    below = _fact(facts, "Strictly below the line")
    if total and not _has_fact_number(answer, total):
        lines.append(f"The season total is {total}.")
    if line and not _has_fact_number(answer, line):
        lines.append(f"The payment line is {line}.")
    if below and not below_result_stated(answer, below):
        lines.append(f"Strictly below the line: {below}.")
    return lines


def higher_total_sentence(answer: str, facts: list[dict]) -> str | None:
    """The verified total-repaid sentence when that is the only payment gap. None means do not append."""
    if not _fact(facts, "Relief status").startswith("Relief applied"):
        return None
    text = answer or ""
    unchanged = re.search(
        r"number of (?:your |the )?payments does not change|"
        r"does not change the (?:total )?number of (?:your |the )?payments|"
        r"number of payments stays the same|same number of payments|not pay fewer",
        text,
        re.IGNORECASE,
    )
    if unchanged is None:
        return None
    if re.search(r"next 3 payments", text, re.IGNORECASE) is None:
        return None
    if re.search(r"30\s*%", text) is None:
        return None
    if re.search(r"slightly higher|total repaid is higher|total repaid goes up|extra cost", text, re.IGNORECASE):
        return None
    before = _fact(facts, "Total repaid before")
    after = _fact(facts, "Total repaid after")
    return (
        f"Total repaid is {before} before and {after} after, so the total repaid is slightly higher."
    )


def debt_not_erased_sentence(answer: str, facts: list[dict]) -> str | None:
    """The verified debt sentence when a true payment answer left it out. None means do not append."""
    if not _fact(facts, "Relief status").startswith("Relief applied"):
        return None
    text = answer or ""
    if re.search(r"does not erase", text, re.IGNORECASE):
        return None
    if re.search(r"debt is cancelled|debt is canceled|is forgiven|is waived", text, re.IGNORECASE):
        return None
    unchanged = re.search(
        r"number of (?:your |the )?payments does not change|"
        r"does not change the (?:total )?number of (?:your |the )?payments|"
        r"number of payments stays the same|same number of payments|not pay fewer",
        text,
        re.IGNORECASE,
    )
    if unchanged is None or re.search(r"next 3 payments", text, re.IGNORECASE) is None:
        return None
    if re.search(r"30\s*%", text) is None:
        return None
    return "Relief does not erase the debt."


def states_why_relief_did_or_did_not_apply(answer: str, facts: list[dict]) -> bool:
    """A why-relief answer has to show the season total, the payment line, and the strictly-below result."""
    if not _has_fact_number(answer, _fact(facts, "Season total")):
        return False
    if not _has_fact_number(answer, _fact(facts, "Payment line")):
        return False
    return below_result_stated(answer, _fact(facts, "Strictly below the line"))


def states_how_payments_change(answer: str, facts: list[dict]) -> bool:
    """Say the next 3 payments and the percent, and that total repaid is slightly higher when relief applies."""
    text = answer or ""
    unchanged = re.search(
        r"number of (?:your |the )?payments does not change|"
        r"does not change the (?:total )?number of (?:your |the )?payments|"
        r"number of payments stays the same|same number of payments|not pay fewer",
        text,
        re.IGNORECASE,
    )
    if unchanged is None:
        return False
    applied = _fact(facts, "Relief status").startswith("Relief applied")
    if not applied:
        return re.search(r"slightly higher", text, re.IGNORECASE) is None
    if re.search(r"next 3 payments", text, re.IGNORECASE) is None:
        return False
    if re.search(r"30\s*%", text) is None:
        return False
    if re.search(r"does not erase", text, re.IGNORECASE) is None:
        return False
    return (
        re.search(r"slightly higher|total repaid is higher|total repaid goes up|extra cost", text, re.IGNORECASE)
        is not None
    )


def states_that_the_chance_is_advisory(answer: str, facts: list[dict]) -> bool:
    """Before week 12 the chance answer has to say advisory and rough. Later, it still must not treat the chance as the decision."""
    text = (answer or "").lower()
    try:
        week = int(_fact(facts, "Week"))
    except ValueError:
        return False
    if week < 12:
        return "advisory" in text and "rough" in text
    if "advisory" in text:
        return True
    return (
        re.search(
            r"does not decide|did not decide|never by the probability|not a guarantee|not on this chance",
            text,
        )
        is not None
    )


def forbidden_claim(answer: str) -> str | None:
    """Deny rules for a rephrase that has no assistant facts pack. None means the text may stand."""
    if claims_fewer_payments(answer):
        return "semantic:fewer-payments"
    if blames_relief_on_something_other_than_final_rainfall(answer):
        return "semantic:wrong-cause"
    if makes_a_forbidden_promise(answer):
        return "semantic:promise"
    if gives_advice(answer):
        return "semantic:advice"
    if predicts_beyond_the_given_chance(answer):
        return "semantic:prediction"
    return None


_COVERAGE = re.compile(
    r"yes[, ]+it covers|it does cover|covers your coconut|covers coconut|coconut is covered|"
    r"coconut farm is covered|covers typhoon|typhoon is covered|typhoon damage is covered|"
    r"pays for typhoon|covers the dry season|covers the dry-season|dry season crop is covered|"
    r"dry-season crop is covered|includes the dry season|also covers",
    re.IGNORECASE,
)


def implies_coverage(answer: str) -> bool:
    """True when the text says coconut, typhoon losses, or the dry-season crop are covered."""
    return _COVERAGE.search(answer or "") is not None


def states_the_scope(answer: str) -> bool:
    text = (answer or "").lower()
    return "wet-season rice" in text and "does not cover" in text and "june to october" in text


def semantic_failure(answer: str, facts: list[dict], intent: str) -> str | None:
    """Why an assistant answer is discarded. None means the semantic rules accept it."""
    reason = forbidden_claim(answer)
    if reason is not None:
        return reason
    if claims_a_cut_when_this_season_has_no_relief(answer, facts):
        return "semantic:cut-without-relief"
    if intent == "why" and not states_why_relief_did_or_did_not_apply(answer, facts):
        return "semantic:why-missing"
    if intent == "payments" and not states_how_payments_change(answer, facts):
        return "semantic:payment-missing"
    if intent == "chance" and not states_that_the_chance_is_advisory(answer, facts):
        return "semantic:chance-missing"
    if intent == "scope" and implies_coverage(answer):
        return "semantic:coverage"
    if intent == "scope" and not states_the_scope(answer):
        return "semantic:scope-missing"
    return None
