"""Deterministic generator for a synthetic Citizen-Space-style export.

Test infrastructure, not shipped code - it lives under tests/, not in a
package, because nothing outside a test ever needs to run it. Its whole
value is determinism: the same seed always produces a byte-identical
export.csv, so a large fixture never has to be committed to be
reproducible. Ground truth (GroundTruth, below) is computed alongside
the row data as it is generated, not recovered afterwards by re-reading
the file, so it can never drift from what was actually written.
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
from pathlib import Path

import yaml
from cip.core.models.ids import response_id as compute_response_id
from cip.core.models.ids import submission_id as compute_submission_id
from pydantic import BaseModel, ConfigDict

CONSULTATION_ID = "generated-consultation"
MANIFEST_VERSION = 1

METADATA_HEADERS = [
    "Response ID",
    "Submitted",
    "Name",
    "Email",
    "Organisation",
    "Postcode",
    "Are you responding as an individual or on behalf of an organisation?",
]

# Every question is free text - there are no closed questions to encode.
QUESTIONS: tuple[tuple[str, str], ...] = (
    ("q1", "What is your overall view of the proposal?"),
    ("q2", "Do you have any comments on the proposed timeline?"),
    ("q3", "What impact, if any, will this have on you or your community?"),
    ("q4", "Do you have suggestions for how the proposal could be improved?"),
    ("q5", "What are your views on the proposed location?"),
    ("q6", "Do you have any concerns about traffic or access?"),
    ("q7", "What are your views on the environmental impact?"),
    ("q8", "Do you have any comments on the consultation process itself?"),
    ("q9", "Is there anything else you would like the council to consider?"),
    ("q10", "Do you have any further comments?"),
)
QUESTION_HEADERS = [text for _key, text in QUESTIONS]

FIRST_NAMES = [
    "Alice",
    "Bob",
    "Carol",
    "David",
    "Elena",
    "Frank",
    "Grace",
    "Hassan",
    "Isla",
    "James",
    "Kavya",
    "Liam",
    "Maria",
    "Noah",
    "Olivia",
    "Priya",
    "Quentin",
    "Rosa",
    "Sam",
    "Tara",
]
LAST_NAMES = [
    "Green",
    "Carter",
    "Diaz",
    "Foster",
    "Lee",
    "Kim",
    "Nguyen",
    "Patel",
    "Muller",
    "Brien",
    "Silva",
    "Johnson",
    "Novak",
    "Andersen",
    "Rossi",
]
ORGANISATIONS = [
    "Riverside Residents Association",
    "Greenfield Traders Group",
    "Oakwood Parish Council",
    "Hillside Cycling Club",
    "Downtown Business Forum",
]
# Weighted toward individuals, per the domain rule that most respondents
# to a public consultation are private individuals, not organisations.
RESPONDENT_LABELS = [
    "An individual",
    "An individual",
    "An individual",
    "An individual",
    "An individual",
    "An individual",
    "An individual",
    "On behalf of an organisation",
    "A public body",
    "Prefer not to say",
]
OPENERS = [
    "Overall, ",
    "Having read the consultation, ",
    "As someone who lives locally, ",
    "Broadly speaking, ",
    "After some thought, ",
    "On balance, ",
    "Looking at the details, ",
    "In summary, ",
]
SUBJECTS = [
    "the new cycle lane",
    "the proposed housing development",
    "the traffic calming measures",
    "the school expansion",
    "the park redesign",
    "the parking changes",
    "the town centre proposals",
    "the flood defences",
    "the bus route changes",
    "the new footpath",
    "the tree removal plan",
    "the library relocation",
    "the leisure centre upgrade",
    "the road closures",
    "the community hall proposal",
]
STANCES = ["strongly support", "support", "have concerns about", "oppose", "am unsure about"]
REASONS = [
    "it will improve safety",
    "it may increase congestion",
    "local residents were not consulted enough",
    "it protects green space",
    "the cost seems too high",
    "it will benefit the local economy",
    "more information is needed first",
    "it sets a poor precedent",
    "it matches what most residents asked for",
    "the timing is badly chosen",
    "it will improve accessibility",
    "the evidence base seems thin",
    "similar schemes have worked well elsewhere",
    "it does not go far enough",
    "it addresses a long-standing problem",
]
CLOSERS = [
    "",
    " I hope this is taken into account.",
    " I would welcome further clarification.",
    " Thank you for considering my views.",
    " I look forward to seeing the outcome.",
    " Please keep residents informed.",
]

# Real campaigns supply suggested wording for one question and let people
# write the rest themselves - so only the templated question varies by a
# single slot, never the whole answer.
CAMPAIGN_TEMPLATE = (
    "Please reconsider this proposal - it will negatively affect {topic} in our neighbourhood."
)
CAMPAIGN_TOPICS = [
    "wildlife",
    "traffic safety",
    "local businesses",
    "green spaces",
    "house prices",
    "air quality",
    "school places",
]

# Occasionally reused verbatim, to plant guaranteed exact-duplicate text
# independent of the campaign mechanism above.
CANNED_EXACT_PHRASES = [
    "This proposal will damage local wildlife and green spaces.",
    "I fully support this initiative and hope it proceeds quickly.",
    "More detail is needed before residents can properly comment.",
    "This is a positive step for the whole community.",
]

# Centred on 3-4 out of ten to twelve questions, matching real answer rates.
ANSWERS_PER_ROW_CHOICES = [2, 3, 3, 3, 4, 4, 5]
P_MISSING_ID = 0.03
P_DUPLICATE_ID = 0.02
P_EXACT_PHRASE = 0.05


class ExactDuplicateGroup(BaseModel):
    model_config = ConfigDict(frozen=True)

    size: int
    response_ids: tuple[str, ...]


class Campaign(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    size: int
    question_key: str
    member_response_ids: tuple[str, ...]


class QuarantinedRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    row: int
    reason: str


class GroundTruth(BaseModel):
    """The exact, checkable outcome a correct ingestion run over this
    export must produce.

    A fixture without this is just a file that might parse - it proves
    nothing about whether ingestion got the numbers right. Every count
    here is accumulated while the row data is being generated, never
    recomputed afterwards by re-reading the CSV, so it cannot silently
    drift from what generate_export actually wrote.
    """

    model_config = ConfigDict(frozen=True)

    submissions_expected: int
    responses_expected: int
    empty_cells: int
    exact_duplicate_groups: tuple[ExactDuplicateGroup, ...] = ()
    campaigns: tuple[Campaign, ...] = ()
    quarantine_expected: tuple[QuarantinedRow, ...] = ()


def _sentence(rng: random.Random) -> str:
    opener = rng.choice(OPENERS)
    sentence = (
        f"{opener}I {rng.choice(STANCES)} {rng.choice(SUBJECTS)} because {rng.choice(REASONS)}."
    )
    return sentence + rng.choice(CLOSERS)


def _campaign_sentence(rng: random.Random) -> str:
    return CAMPAIGN_TEMPLATE.format(topic=rng.choice(CAMPAIGN_TOPICS))


def _plan_campaigns(rng: random.Random, valid_row_indices: list[int]) -> list[dict[str, object]]:
    """Decide campaign membership before any row content is written, so
    membership never depends on, or accidentally overlaps with, content
    generated later in the same pass.
    """
    if len(valid_row_indices) < 20:
        return []

    remaining = list(valid_row_indices)
    rng.shuffle(remaining)
    num_campaigns = min(1 + len(valid_row_indices) // 150, 3)

    plans: list[dict[str, object]] = []
    for i in range(num_campaigns):
        size = rng.randint(5, max(5, min(30, len(remaining) // 4)))
        if size > len(remaining):
            break
        members = sorted(remaining[:size])
        remaining = remaining[size:]
        question_key, _text = rng.choice(QUESTIONS)
        plans.append(
            {"id": f"campaign-{i + 1:03d}", "question_key": question_key, "members": members}
        )
    return plans


def generate_export(rows: int, seed: int, out_dir: Path) -> GroundTruth:
    """Write export.csv, manifest.yaml and expected.json under out_dir,
    and return the same ground truth recorded in expected.json.

    Deterministic in (rows, seed) alone: the same two values always
    produce a byte-identical export.csv, because generation draws
    exclusively from a random.Random(seed) instance rather than global
    state or wall-clock time.
    """
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Pass 1: decide validity for every row - missing or duplicate ids
    # quarantine a row; everything else is a real submission.
    row_ids: list[str | None] = []
    quarantine: list[QuarantinedRow] = []
    assigned_ids: list[str] = []
    valid_row_indices: list[int] = []

    for i in range(rows):
        roll = rng.random()
        if roll < P_MISSING_ID:
            row_ids.append(None)
            quarantine.append(QuarantinedRow(row=i + 1, reason="missing_submission_id"))
        elif roll < P_MISSING_ID + P_DUPLICATE_ID and assigned_ids:
            row_ids.append(rng.choice(assigned_ids))
            quarantine.append(QuarantinedRow(row=i + 1, reason="duplicate_submission_id"))
        else:
            new_id = f"RESP-{i + 1:05d}"
            row_ids.append(new_id)
            assigned_ids.append(new_id)
            valid_row_indices.append(i)

    # Pass 2: plan campaigns over the valid rows only.
    valid_row_index_set = set(valid_row_indices)
    campaign_plans = _plan_campaigns(rng, valid_row_indices)
    campaign_question_by_row: dict[int, str] = {}
    for plan in campaign_plans:
        for member in plan["members"]:  # type: ignore[union-attr]
            campaign_question_by_row[member] = plan["question_key"]  # type: ignore[assignment]

    # Pass 3: generate row content, accumulating ground truth as we go.
    text_usage: dict[str, list[tuple[int, str]]] = {}
    csv_rows: list[dict[str, str]] = []
    submissions_expected = 0
    responses_expected = 0
    empty_cells = 0

    for i in range(rows):
        response_id_value = row_ids[i]
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        row: dict[str, str] = {
            "Response ID": response_id_value or "",
            "Submitted": f"2024-03-{1 + (i % 28):02d} {8 + (i % 10):02d}:{(i * 7) % 60:02d}:00",
            "Name": f"{first} {last}",
            "Email": f"{first.lower()}.{last.lower()}{i}@example.com",
            "Organisation": rng.choice(ORGANISATIONS) if rng.random() < 0.15 else "",
            "Postcode": f"{rng.choice(['SW1A', 'EC1A', 'M1', 'B1', 'LS1', 'G1'])} {rng.randint(1, 9)}AA",
            "Are you responding as an individual or on behalf of an organisation?": rng.choice(
                RESPONDENT_LABELS
            ),
        }

        forced_question_key = campaign_question_by_row.get(i)
        answered_keys: set[str] = set()
        if forced_question_key is not None:
            answered_keys.add(forced_question_key)
        num_answers = rng.choice(ANSWERS_PER_ROW_CHOICES)
        pool = [key for key, _text in QUESTIONS if key not in answered_keys]
        rng.shuffle(pool)
        answered_keys.update(pool[: max(0, num_answers - len(answered_keys))])

        row_empty = 0
        row_answered = 0
        for key, text in QUESTIONS:
            if key in answered_keys:
                if key == forced_question_key:
                    answer = _campaign_sentence(rng)
                elif rng.random() < P_EXACT_PHRASE:
                    answer = rng.choice(CANNED_EXACT_PHRASES)
                else:
                    answer = _sentence(rng)
                row[text] = answer
                row_answered += 1
                if i in valid_row_index_set:
                    text_usage.setdefault(answer, []).append((i, text))
            else:
                row[text] = ""
                row_empty += 1

        csv_rows.append(row)

        if i in valid_row_index_set:
            submissions_expected += 1
            responses_expected += row_answered
            empty_cells += row_empty

    # Write export.csv, then hash it: ids are computed from the file
    # that actually exists on disk, the same way a real parser would.
    fieldnames = METADATA_HEADERS + QUESTION_HEADERS
    csv_path = out_dir / "export.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for row in csv_rows:
            writer.writerow(row)

    source_sha256 = hashlib.sha256(csv_path.read_bytes()).hexdigest()

    submission_ids: dict[int, str] = {
        i: compute_submission_id(CONSULTATION_ID, source_sha256, row_ids[i] or "")
        for i in valid_row_indices
    }

    def _response_id_for(row_index: int, column: str) -> str:
        return compute_response_id(submission_ids[row_index], column)

    exact_duplicate_groups = tuple(
        ExactDuplicateGroup(
            size=len(occurrences),
            response_ids=tuple(
                sorted(_response_id_for(row_index, column) for row_index, column in occurrences)
            ),
        )
        for occurrences in text_usage.values()
        if len(occurrences) >= 2
    )

    question_header_by_key = {key: text for key, text in QUESTIONS}
    campaigns = tuple(
        Campaign(
            id=str(plan["id"]),
            size=len(plan["members"]),  # type: ignore[arg-type]
            question_key=str(plan["question_key"]),
            member_response_ids=tuple(
                _response_id_for(member, question_header_by_key[str(plan["question_key"])])
                for member in plan["members"]  # type: ignore[union-attr]
            ),
        )
        for plan in campaign_plans
    )

    # Write manifest.yaml: same column shape as the golden fixture,
    # scaled to ten questions.
    columns: dict[str, object] = {
        "Response ID": {"role": "submission_id"},
        "Submitted": {"role": "submitted_at"},
        "Name": {"role": "identity", "handling": "drop"},
        "Email": {"role": "identity", "handling": "hash"},
        "Organisation": {"role": "identity", "handling": "keep"},
        "Postcode": {"role": "identity", "handling": "coarsen"},
        "Are you responding as an individual or on behalf of an organisation?": {
            "role": "respondent_type"
        },
    }
    for key, text in QUESTIONS:
        columns[text] = {"role": "free_text", "question": key}

    manifest = {
        "version": MANIFEST_VERSION,
        "consultation": CONSULTATION_ID,
        "title": "Generated Fixture Consultation",
        "source": "csv",
        "encoding": "utf-8",
        "sheet": None,
        "columns": columns,
        "questions": [
            {"key": key, "text": text, "position": position}
            for position, (key, text) in enumerate(QUESTIONS)
        ],
        "source_sha256": source_sha256,
    }
    (out_dir / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )

    ground_truth = GroundTruth(
        submissions_expected=submissions_expected,
        responses_expected=responses_expected,
        empty_cells=empty_cells,
        exact_duplicate_groups=exact_duplicate_groups,
        campaigns=campaigns,
        quarantine_expected=tuple(quarantine),
    )
    (out_dir / "expected.json").write_text(
        json.dumps(ground_truth.model_dump(mode="json"), indent=2), encoding="utf-8"
    )

    return ground_truth
