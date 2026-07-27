from ..case_schema import (
    Backtrack,
    Case,
    Compaction,
    GoldConstraint,
    GoldSurvival,
    IntentShift,
    Segment,
    T,
)


TURNS = [
    T(
        "user",
        "I want to brainstorm an evaluation method for a retrieval agent over a licensed collection of internal papers. "
        "The evaluation should tell us whether a retrieved passage actually supports an answer, not only whether a model sounds fluent.",
    ),
    T(
        "assistant",
        "Let us start with the research question. I would compare retrieval quality, evidence support, and answer usefulness as separate dimensions. "
        "The first draft can stay small enough to inspect by hand.",
    ),
    T(
        "user",
        "For the first benchmark, should a query ask for a single fact, a comparison across papers, or a short synthesis? "
        "I want the task mix to reveal where retrieval fails.",
    ),
    T(
        "assistant",
        "Use all three task families. Single-fact queries expose missed passages, comparison queries expose incomplete coverage, and synthesis queries expose unsupported joins. "
        "Each query should carry a small set of evidence-bearing passages for later review.",
    ),
    T(
        "user",
        "How should we sample the questions? A random slice may overrepresent easy papers, while a hand-picked list may hide the long tail.",
    ),
    T(
        "assistant",
        "Stratify by document age, topic, and expected retrieval difficulty, then reserve a held-out slice for the final report. "
        "We can pilot the strata before committing to a larger annotation pass.",
    ),
    T(
        "user",
        "The benchmark framing is getting broad. Let us move to the annotation protocol: what exactly should a reviewer mark when a passage supports an answer only partially?",
    ),
    T(
        "assistant",
        "For each answer claim, ask the reviewer to mark entailment, contradiction, or insufficient evidence and to attach the smallest supporting quote. "
        "A partial match should remain visible rather than being rounded up to a binary hit.",
    ),
    T(
        "user",
        "I would like two reviewers on difficult examples. We need a rule for disagreements that does not silently turn a disputed label into a clean score.",
    ),
    T(
        "assistant",
        "Record both labels, the adjudicated label, and the reason for the decision. The report can show agreement before adjudication so readers see where the rubric is unstable.",
    ),
    T(
        "user",
        "The corpus license prohibits redistributing raw passages. We can keep document identifiers and hashes in the evaluation record, but not the source text.",
    ),
    T(
        "assistant",
        "That makes the evidence ledger a local review surface: store a document id, a passage hash, offsets for the private reviewer, and the final label. "
        "The shared result can publish aggregate counts without copying passages.",
    ),
    T(
        "user",
        "Can we freeze a few positive, negative, and borderline examples before the main annotation? The examples should teach the rubric without becoming a hidden test set.",
    ),
    T(
        "assistant",
        "Yes. Make the examples a training packet, keep them out of the held-out score, and log every rubric revision. "
        "The next question is how to summarize uncertainty in the pilot results.",
    ),
    T(
        "user",
        "A preregistered query-difficulty stratification belongs in the protocol. For each stratum, I want the same retrieval and evidence-support measurements.",
    ),
    T(
        "assistant",
        "We can report recall at k, evidence precision, and unsupported-claim rate within each stratum, then aggregate with the stratum weights fixed before scoring. "
        "That keeps the headline number from hiding a difficult slice.",
    ),
    T(
        "user",
        "The annotation budget is capped at $200. Please design a pilot that estimates the signal before we spend the whole budget.",
    ),
    T(
        "assistant",
        "Use a small balanced pilot, estimate variance for each metric, and spend the remaining labels on strata whose intervals are widest. "
        "A paired bootstrap over queries can show uncertainty without pretending the examples are independent documents.",
    ),
    T(
        "user",
        "Should we compare two retrievers with a significance test, or is a confidence interval and an effect-size table more honest for this first pass?",
    ),
    T(
        "assistant",
        "Prefer paired differences, confidence intervals, and an effect-size table in the first report. A significance test can be a secondary view after the sampling unit and pairing rule are stable.",
    ),
    T(
        "user",
        "The pilot exposed disagreement in the evidence labels. Return to the annotation protocol and repair the rubric before we finalize the statistical plan.",
    ),
    T(
        "assistant",
        "Returning to the rubric, I would add a separate label for mixed evidence, require a quote for every positive claim, and route only unresolved examples to adjudication. "
        "The statistical table should report the revised label definitions next to its intervals.",
    ),
    T(
        "user",
        "The final checklist should say: Do not change the held-out test split after analysis begins. Also record the reviewer pair and every adjudication reason.",
    ),
    T(
        "assistant",
        "The checklist now freezes the split, preserves reviewer provenance, and separates raw evidence from publishable aggregates. "
        "It also records rubric version, retrieval configuration, and the paired-bootstrap seed.",
    ),
    T(
        "user",
        "What belongs in the research report so another team can reproduce the method without receiving the licensed passages?",
    ),
    T(
        "assistant",
        "Publish the query schema, stratum definitions, rubric version, hashes, aggregate metrics, confidence intervals, and an adjudication summary. "
        "Keep passage text and reviewer-only offsets inside the licensed environment.",
    ),
    T(
        "user",
        "Good. We have a benchmark question, an annotation protocol, a statistical pilot, and a return to the protocol where the pilot found a real flaw.",
    ),
    T(
        "assistant",
        "That is a coherent evaluation-method draft: the research question stays visible, the drift is recorded, and the return makes the rubric change auditable before any headline score is published.",
    ),
]


CASE = Case(
    case_id="c7",
    title="Research-method brainstorm: retrieval-agent evaluation with an auditable return",
    turns=TURNS,
    segments=[
        Segment("A — benchmark question", 0, 6),
        Segment("B — annotation protocol", 7, 13),
        Segment("C — statistical pilot", 14, 20),
        Segment("B — return to annotation protocol", 21, 27),
    ],
    constraints=[
        GoldConstraint(turn=10, text="The corpus license prohibits redistributing raw passages."),
        GoldConstraint(turn=16, text="The annotation budget is capped at $200."),
        GoldConstraint(
            turn=14,
            text="A preregistered query-difficulty stratification belongs in the protocol.",
        ),
        GoldConstraint(
            turn=22,
            text="Do not change the held-out test split after analysis begins.",
        ),
    ],
    backtracks=[
        Backtrack(
            from_segment=3,
            to_segment=1,
            note="The pilot exposed label disagreement, so the brainstorm returns to the annotation rubric before reporting.",
        ),
    ],
    compaction=Compaction(
        kept_turns=[10, 11, 20, 21, 22, 23, 24, 25, 26, 27],
        summary=(
            "The brainstorm framed retrieval-agent evaluation around task families and evidence labels, then drafted annotation guidance and a statistical pilot. "
            "The annotation budget has a ceiling of 200 dollars, and the later discussion returned to rubric adjudication. "
            "License handling stores document identifiers and hashes rather than raw passages."
        ),
    ),
    survival=[
        GoldSurvival(constraint=0, status="present"),
        GoldSurvival(constraint=1, status="reframed"),
        GoldSurvival(constraint=2, status="absent"),
    ],
    intent_shifts=[
        IntentShift(
            segment=1,
            kind="drift",
            cause_turn=6,
            note="The benchmark question drifts into designing an annotation protocol.",
        ),
        IntentShift(
            segment=2,
            kind="drift",
            cause_turn=13,
            note="The annotation rubric drifts into statistical pilot design.",
        ),
        IntentShift(
            segment=3,
            kind="return",
            cause_turn=20,
            note="Pilot disagreement returns the brainstorm to the annotation protocol.",
        ),
    ],
)
