from __future__ import annotations

import argparse
import os
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json


def require_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required, e.g. postgresql://user@localhost:5432/oce_sim")
    return url


DEFAULT_DUTTON_SOURCE_ID = "64178262-0f4a-4f48-b77f-ee012a82a828"


@dataclass(frozen=True)
class ScenarioSpec:
    key: str
    title: str
    region: str
    # Keywords used to pull short evidence snippets from the book
    keywords: Sequence[str]
    # Minimal clinical scenario seed (we keep it generic + safe)
    patient_seed: str


SCENARIOS: List[ScenarioSpec] = [
    ScenarioSpec(
        key="shoulder_rotator_cuff",
        title="Shoulder pain (suspected rotator cuff tendinopathy/impingement)",
        region="shoulder",
        keywords=["rotator cuff", "impingement", "painful arc", "supraspinatus", "Neer", "Hawkins"],
        patient_seed="45-year-old who reports lateral shoulder pain worse with overhead reaching and dressing.",
    ),
    ScenarioSpec(
        key="shoulder_adhesive_capsulitis",
        title="Shoulder stiffness (suspected adhesive capsulitis)",
        region="shoulder",
        keywords=["adhesive capsulitis", "frozen shoulder", "capsular pattern", "external rotation"],
        patient_seed="52-year-old with progressive shoulder stiffness and night pain over 3 months.",
    ),
    ScenarioSpec(
        key="elbow_lateral_epicondylalgia",
        title="Elbow pain (suspected lateral epicondylalgia)",
        region="elbow",
        keywords=["lateral epicondyl", "tennis elbow", "Cozen", "grip", "wrist extension"],
        patient_seed="38-year-old with lateral elbow pain with gripping and wrist extension tasks.",
    ),
    ScenarioSpec(
        key="wrist_carpal_tunnel",
        title="Hand symptoms (suspected carpal tunnel syndrome)",
        region="hand_wrist",
        keywords=["carpal tunnel", "median nerve", "Phalen", "Tinel", "thenar"],
        patient_seed="41-year-old with night paresthesia in thumb/index/middle fingers and reduced grip.",
    ),
    ScenarioSpec(
        key="hip_oa",
        title="Hip pain (suspected osteoarthritis)",
        region="hip",
        keywords=["hip osteoarthritis", "joint space", "capsular pattern", "groin pain"],
        patient_seed="67-year-old with gradual onset anterior hip/groin pain and reduced walking tolerance.",
    ),
    ScenarioSpec(
        key="knee_acl",
        title="Knee injury (suspected ACL tear)",
        region="knee",
        keywords=["ACL", "anterior cruciate", "Lachman", "pivot shift", "hemarthrosis"],
        patient_seed="22-year-old athlete with twisting injury, pop, swelling, and instability with cutting.",
    ),
    ScenarioSpec(
        key="knee_pf_pain",
        title="Anterior knee pain (suspected patellofemoral pain)",
        region="knee",
        keywords=["patellofemoral", "anterior knee pain", "stairs", "squat", "Q angle"],
        patient_seed="24-year-old runner with anterior knee pain worse descending stairs and with squats.",
    ),
    ScenarioSpec(
        key="ankle_sprain",
        title="Ankle injury (suspected lateral ankle sprain)",
        region="ankle_foot",
        keywords=["ankle sprain", "ATFL", "anterior drawer", "Ottawa", "inversion"],
        patient_seed="29-year-old with inversion injury playing sport, swelling, and lateral ankle tenderness.",
    ),
    ScenarioSpec(
        key="plantar_fasciopathy",
        title="Heel pain (suspected plantar fasciopathy)",
        region="ankle_foot",
        keywords=["plantar fascia", "heel pain", "first steps", "windlass", "calcaneus"],
        patient_seed="46-year-old with plantar heel pain worse on first steps in the morning.",
    ),
    ScenarioSpec(
        key="low_back_pain_mechanical",
        title="Low back pain (mechanical, no red flags on initial screen)",
        region="lumbar_spine",
        keywords=["low back pain", "lumbar", "centralization", "extension", "flexion"],
        patient_seed="36-year-old with acute low back pain after lifting, no neurological symptoms initially.",
    ),
    ScenarioSpec(
        key="cervical_radiculopathy",
        title="Neck + arm symptoms (suspected cervical radiculopathy)",
        region="cervical_spine",
        keywords=["radiculopathy", "Spurling", "dermatome", "myotome", "reflex"],
        patient_seed="48-year-old with neck pain radiating to arm with numbness in a dermatomal pattern.",
    ),
    ScenarioSpec(
        key="tmj_pain",
        title="Jaw pain (suspected temporomandibular disorder)",
        region="tmj",
        keywords=["temporomandibular", "TMJ", "jaw", "click", "opening"],
        patient_seed="30-year-old with jaw clicking and pain with chewing, limited opening on bad days.",
    ),
    # Shoulder / upper quarter
    ScenarioSpec(
        key="shoulder_instability_anterior",
        title="Shoulder instability (suspected anterior instability/dislocation history)",
        region="shoulder",
        keywords=["apprehension", "relocation", "instability", "Bankart", "dislocation"],
        patient_seed="19-year-old with recurrent shoulder giving-way episodes after a first-time dislocation playing sport.",
    ),
    ScenarioSpec(
        key="ac_joint_sprain",
        title="AC joint injury (suspected AC sprain)",
        region="shoulder",
        keywords=["acromioclavicular", "AC joint", "cross-body", "step deformity"],
        patient_seed="27-year-old fell onto the shoulder and now has focal AC joint pain with cross-body adduction.",
    ),
    # Elbow / forearm
    ScenarioSpec(
        key="elbow_medial_epicondylalgia",
        title="Elbow pain (suspected medial epicondylalgia)",
        region="elbow",
        keywords=["medial epicondyl", "golfer", "wrist flexion", "pronation"],
        patient_seed="42-year-old with medial elbow pain aggravated by gripping and resisted wrist flexion/pronation.",
    ),
    ScenarioSpec(
        key="ulnar_neuropathy_cubital_tunnel",
        title="Hand symptoms (suspected ulnar neuropathy at cubital tunnel)",
        region="elbow",
        keywords=["ulnar nerve", "cubital tunnel", "ring finger", "small finger", "Tinel"],
        patient_seed="35-year-old with numbness in ring/small fingers worse with prolonged elbow flexion.",
    ),
    # Hand / wrist
    ScenarioSpec(
        key="de_quervain",
        title="Radial wrist pain (suspected De Quervain tenosynovitis)",
        region="hand_wrist",
        keywords=["De Quervain", "Finkelstein", "APL", "EPB", "radial styloid"],
        patient_seed="33-year-old with radial wrist/thumb pain after repetitive lifting, worse with thumb motion.",
    ),
    ScenarioSpec(
        key="thumb_cmc_oa",
        title="Thumb base pain (suspected CMC osteoarthritis)",
        region="hand_wrist",
        keywords=["CMC", "thumb", "grind test", "osteoarthritis"],
        patient_seed="62-year-old with thumb base pain and difficulty opening jars and pinching.",
    ),
    # Hip
    ScenarioSpec(
        key="hip_fai",
        title="Hip pain (suspected femoroacetabular impingement)",
        region="hip",
        keywords=["FAI", "impingement", "FADIR", "groin", "hip flexion"],
        patient_seed="26-year-old with groin pain provoked by deep hip flexion and sport-related cutting.",
    ),
    ScenarioSpec(
        key="greater_trochanteric_pain",
        title="Lateral hip pain (suspected greater trochanteric pain syndrome)",
        region="hip",
        keywords=["greater trochanter", "gluteus medius", "Trendelenburg", "bursitis"],
        patient_seed="54-year-old with lateral hip pain worse side-lying and prolonged walking.",
    ),
    # Knee
    ScenarioSpec(
        key="knee_meniscus",
        title="Knee pain (suspected meniscal injury)",
        region="knee",
        keywords=["meniscus", "McMurray", "Thessaly", "locking", "joint line"],
        patient_seed="34-year-old with joint-line pain and intermittent catching after a twisting movement.",
    ),
    ScenarioSpec(
        key="knee_oa",
        title="Knee pain (suspected osteoarthritis)",
        region="knee",
        keywords=["knee osteoarthritis", "crepitus", "stiffness", "varus"],
        patient_seed="70-year-old with gradual knee pain and morning stiffness improving with movement.",
    ),
    ScenarioSpec(
        key="itb_syndrome",
        title="Lateral knee pain (suspected iliotibial band syndrome)",
        region="knee",
        keywords=["iliotibial", "ITB", "Noble", "running", "lateral knee"],
        patient_seed="28-year-old runner with lateral knee pain that worsens after 10–15 minutes of running.",
    ),
    # Ankle/foot
    ScenarioSpec(
        key="achilles_tendinopathy",
        title="Posterior ankle pain (suspected Achilles tendinopathy)",
        region="ankle_foot",
        keywords=["Achilles", "tendinopathy", "heel raise", "calf", "load"],
        patient_seed="39-year-old with Achilles pain and morning stiffness worse with running and jumping.",
    ),
    ScenarioSpec(
        key="ankle_fracture_ottawa",
        title="Acute ankle injury (rule out fracture using Ottawa ankle rules)",
        region="ankle_foot",
        keywords=["Ottawa", "malleolus", "navicular", "base of fifth", "fracture"],
        patient_seed="31-year-old with acute ankle injury, difficulty weight-bearing, and bony tenderness.",
    ),
    ScenarioSpec(
        key="metatarsalgia",
        title="Forefoot pain (suspected metatarsalgia)",
        region="ankle_foot",
        keywords=["metatarsalgia", "forefoot", "metatarsal heads", "push-off"],
        patient_seed="44-year-old with plantar forefoot pain worse during push-off and prolonged standing.",
    ),
    # Lumbar / pelvis
    ScenarioSpec(
        key="lumbar_disc_radicular",
        title="Low back pain with leg symptoms (suspected lumbar disc herniation/radicular pain)",
        region="lumbar_spine",
        keywords=["straight leg raise", "radicular", "disc", "centralization", "dermatome"],
        patient_seed="40-year-old with low back pain radiating below the knee with paresthesia and pain with sitting.",
    ),
    ScenarioSpec(
        key="lumbar_stenosis",
        title="Leg pain with walking (suspected lumbar spinal stenosis)",
        region="lumbar_spine",
        keywords=["stenosis", "neurogenic claudication", "flexion", "walking tolerance"],
        patient_seed="72-year-old with bilateral leg symptoms and reduced walking tolerance relieved by sitting/flexion.",
    ),
    ScenarioSpec(
        key="sacroiliac_pain",
        title="Buttock pain (suspected sacroiliac joint-related pain)",
        region="sacroiliac_joint",
        keywords=["sacroiliac", "SIJ", "ASLR", "thigh thrust", "compression"],
        patient_seed="32-year-old postpartum with unilateral buttock pain aggravated by transfers and single-leg tasks.",
    ),
    # Cervical
    ScenarioSpec(
        key="cervicogenic_headache",
        title="Headache (suspected cervicogenic headache)",
        region="cervical_spine",
        keywords=["cervicogenic", "headache", "upper cervical", "C1", "C2"],
        patient_seed="37-year-old with unilateral headache provoked by neck positions and sustained posture.",
    ),
    ScenarioSpec(
        key="whiplash",
        title="Neck pain after MVC (whiplash-associated disorder)",
        region="cervical_spine",
        keywords=["whiplash", "WAD", "MVC", "neck pain", "dizziness"],
        patient_seed="29-year-old with neck pain and headaches after a motor vehicle collision 10 days ago.",
    ),
    # Thoracic / rib / posture
    ScenarioSpec(
        key="thoracic_pain_postural",
        title="Mid-back pain (postural/thoracic mobility impairment)",
        region="thoracic_spine",
        keywords=["thoracic", "posture", "kyphosis", "mobilization", "rotation"],
        patient_seed="31-year-old with mid-back ache after prolonged desk work, worse end of day, relieved by movement.",
    ),
    ScenarioSpec(
        key="rib_pain_costovertebral",
        title="Thoracic/rib pain (suspected costovertebral dysfunction)",
        region="thoracic_spine",
        keywords=["costovertebral", "rib", "thoracic", "respiration", "pain"],
        patient_seed="40-year-old with sharp rib pain with deep breathing and trunk rotation after sudden twist.",
    ),
    # Shoulder/neck combined
    ScenarioSpec(
        key="thoracic_outlet_suspected",
        title="Arm symptoms (suspected thoracic outlet syndrome pattern)",
        region="shoulder",
        keywords=["thoracic outlet", "TOS", "Adson", "Roos", "paresthesia"],
        patient_seed="28-year-old with intermittent arm paresthesia and heaviness provoked by overhead positions.",
    ),
    # Knee ligament / tendon
    ScenarioSpec(
        key="knee_mcl_sprain",
        title="Knee injury (suspected MCL sprain)",
        region="knee",
        keywords=["MCL", "valgus", "medial collateral", "sprain"],
        patient_seed="26-year-old with medial knee pain after valgus stress during sport, pain with pivoting.",
    ),
    ScenarioSpec(
        key="knee_pcl",
        title="Knee injury (suspected PCL injury)",
        region="knee",
        keywords=["PCL", "posterior drawer", "posterior sag", "dashboard"],
        patient_seed="30-year-old after car accident with dashboard impact, posterior knee pain and instability.",
    ),
    ScenarioSpec(
        key="patellar_tendinopathy",
        title="Anterior knee pain (suspected patellar tendinopathy)",
        region="knee",
        keywords=["patellar tendon", "jumper", "tendinopathy", "eccentric"],
        patient_seed="21-year-old volleyball player with pain at inferior patellar pole with jumping and stairs.",
    ),
    # Ankle/foot additional
    ScenarioSpec(
        key="posterior_tibial_tendinopathy",
        title="Medial ankle pain (suspected posterior tibial tendon dysfunction early)",
        region="ankle_foot",
        keywords=["posterior tibial", "navicular", "arch", "PTTD"],
        patient_seed="55-year-old with medial ankle pain and fatigue, reports arch collapse sensation with walking.",
    ),
    ScenarioSpec(
        key="hallux_rigidus",
        title="Big toe pain (suspected hallux rigidus)",
        region="ankle_foot",
        keywords=["hallux", "MTP", "rigidus", "osteophyte"],
        patient_seed="58-year-old with dorsal 1st MTP pain and reduced toe-off, worse with stairs and running.",
    ),
    ScenarioSpec(
        key="stress_fracture_risk",
        title="Foot pain (rule out stress fracture risk)",
        region="ankle_foot",
        keywords=["stress fracture", "tenderness", "running", "swelling"],
        patient_seed="19-year-old increased running volume rapidly and now has focal midfoot pain and swelling.",
    ),
    # Hip / pelvis additional
    ScenarioSpec(
        key="hip_labral_suspected",
        title="Hip pain (suspected labral pathology pattern)",
        region="hip",
        keywords=["labral", "click", "FADIR", "groin pain"],
        patient_seed="29-year-old with groin pain, clicking, and pain with pivoting and prolonged sitting.",
    ),
    ScenarioSpec(
        key="hamstring_strain",
        title="Posterior thigh pain (suspected hamstring strain)",
        region="hip",
        keywords=["hamstring", "strain", "sprint", "eccentric"],
        patient_seed="24-year-old sprinter with sudden posterior thigh pain during acceleration, difficulty with running.",
    ),
    # Spine
    ScenarioSpec(
        key="lumbar_spondylolisthesis",
        title="Low back pain in extension (suspected spondylolysis/spondylolisthesis pattern)",
        region="lumbar_spine",
        keywords=["spondylolisthesis", "spondylolysis", "extension", "pars"],
        patient_seed="17-year-old athlete with low back pain worse with extension and sport, improved with rest.",
    ),
    ScenarioSpec(
        key="neck_mechanical_posture",
        title="Neck pain (mechanical/postural without radicular symptoms)",
        region="cervical_spine",
        keywords=["cervical", "posture", "deep neck flexors", "ergonomics"],
        patient_seed="34-year-old with neck pain after prolonged computer work, no arm symptoms.",
    ),
    # Neurodynamic / peripheral nerve
    ScenarioSpec(
        key="sciatic_neural_tension",
        title="Leg symptoms (neural mechanosensitivity / sciatic nerve tension pattern)",
        region="lumbar_spine",
        keywords=["neurodynamic", "SLR", "slump", "nerve tension"],
        patient_seed="32-year-old with posterior thigh/calf symptoms worsened by slump sitting and relieved by posture change.",
    ),
    ScenarioSpec(
        key="median_nerve_neurodynamic",
        title="Arm symptoms (median nerve mechanosensitivity pattern)",
        region="hand_wrist",
        keywords=["median nerve", "ULTT", "neurodynamic", "paresthesia"],
        patient_seed="36-year-old with intermittent hand paresthesia aggravated by sustained wrist/elbow positions at work.",
    ),
]


def fetch_snippets(conn: psycopg.Connection, *, source_id: str, keywords: Sequence[str], max_snippets: int = 3) -> List[str]:
    # Pull a few short text snippets as “evidence hints” to ground the generator.
    # This stays internal to the generator; we do not expose the book verbatim in prompts by default.
    # NOTE: This is best-effort keyword search over extracted text.
    terms = [k.strip() for k in keywords if k.strip()]
    if not terms:
        return []
    where = " OR ".join([f"text ILIKE %s" for _ in terms])
    params = [f"%{t}%" for t in terms]
    with conn.cursor() as cur:
        cur.execute(
            f"""
            select text
            from source_chunks
            where source_id = %s and ({where})
            order by chunk_index asc
            limit 12
            """,
            [source_id, *params],
        )
        rows = cur.fetchall()
    snippets: List[str] = []
    for r in rows:
        t = (r["text"] or "").strip()
        if not t:
            continue
        # Keep only a short excerpt
        snippets.append(t[:700])
    # Deduplicate and cap
    out = []
    seen = set()
    for s in snippets:
        key = s[:120]
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= max_snippets:
            break
    return out


def get_oce_rubric_domain_ids(conn: psycopg.Connection, *, rubric_name: str = "OCE Domains") -> Dict[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select rs.id::text as rubric_set_id
            from rubric_sets rs
            where rs.name = %s
            order by rs.created_at desc
            limit 1
            """,
            (rubric_name,),
        )
        rs = cur.fetchone()
        if not rs:
            raise RuntimeError(f"Missing rubric_set named {rubric_name}. Import Domains PPT first.")

        cur.execute(
            """
            select id::text as id, key
            from rubric_domains
            where rubric_set_id = %s
            """,
            (rs["rubric_set_id"],),
        )
        rows = cur.fetchall()
    return {r["key"]: r["id"] for r in rows}


def get_some_criteria_ids(conn: psycopg.Connection, *, rubric_domain_id: str, limit: int = 6) -> List[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select id::text as id
            from rubric_criteria
            where rubric_domain_id = %s
            order by key asc
            limit %s
            """,
            (rubric_domain_id, limit),
        )
        return [r["id"] for r in cur.fetchall()]


def insert_case(conn: psycopg.Connection, *, title: str, case_type: str, source_id: str, status: str = "draft") -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into cases(title, case_type, source_id, status)
            values (%s, %s, %s, %s)
            returning id::text as id
            """,
            (title, case_type, source_id, status),
        )
        return cur.fetchone()["id"]

def case_exists(conn: psycopg.Connection, *, source_id: str, title: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "select 1 from cases where source_id = %s and title = %s limit 1",
            (source_id, title),
        )
        return cur.fetchone() is not None


def get_case_id(conn: psycopg.Connection, *, source_id: str, title: str) -> Optional[str]:
    with conn.cursor() as cur:
        cur.execute(
            "select id::text as id from cases where source_id = %s and title = %s limit 1",
            (source_id, title),
        )
        row = cur.fetchone()
        return row["id"] if row else None


def ensure_case(conn: psycopg.Connection, *, title: str, case_type: str, source_id: str, status: str) -> str:
    existing = get_case_id(conn, source_id=source_id, title=title)
    if existing:
        return existing
    return insert_case(conn, title=title, case_type=case_type, source_id=source_id, status=status)


def insert_prompts(conn: psycopg.Connection, *, case_id: str, prompts: List[Tuple[int, str, str]]) -> None:
    with conn.cursor() as cur:
        for order_index, prompt_text, prompt_type in prompts:
            cur.execute(
                """
                insert into case_prompts(case_id, order_index, prompt_text, prompt_type)
                values (%s, %s, %s, %s)
                on conflict (case_id, order_index) do update
                set prompt_text = excluded.prompt_text,
                    prompt_type = excluded.prompt_type
                """,
                (case_id, order_index, prompt_text, prompt_type),
            )


def insert_expected_elements(
    conn: psycopg.Connection,
    *,
    case_id: str,
    elements: List[Tuple[str, str, Optional[str]]],  # (importance, expected_text, rubric_criterion_id)
) -> None:
    with conn.cursor() as cur:
        for importance, expected_text, criterion_id in elements:
            cur.execute(
                """
                insert into case_expected_elements(case_id, rubric_criterion_id, expected_text, importance)
                values (%s, %s, %s, %s)
                """,
                (case_id, criterion_id, expected_text, importance),
            )


def build_case1_prompts(spec: ScenarioSpec) -> List[Tuple[int, str, str]]:
    stem = (
        "OSCE-style structured interview (Case 1: Assessment-focused)\n\n"
        "Role/setting: You are the physiotherapist in an outpatient clinic. You are speaking to an examiner.\n"
        "Rules: Answer in order. Be specific to THIS client. Prioritize safety first.\n"
        "Allowed actions (verbalize intent): you may state what you would ask in history, what you would examine, what tests/measures you would use,\n"
        "and when you would refer/escalate. If you need data (vitals/exam findings), state what you would obtain and why.\n\n"
        f"Region: {spec.region}\n"
        f"Client: {spec.patient_seed}\n\n"
        "Answer format for each question:\n"
        "- Headline (≤10s): 1 sentence with your top priority\n"
        "- Bullets (≤45s): top 3 items (then 1–2 backup details if time)\n"
        "- Safety check (≤10s): what would make this unsafe / require escalation\n"
    )
    probes = [
        "Q1 (60s): Accepting the client. Is PT appropriate now? Name your top 2 red flags + 1 key safety decision.",
        "Q2 (45s): Informed consent (plain language). What will you explain + how will you confirm understanding (teach-back)?",
        "Q3 (90s): Assessment plan. Top 3 subjective questions + top 3 objective tests/measures (and why each matters).",
        "Q4 (60s): Clinical impression. 1 working diagnosis + 1 alternative + what finding would change your impression.",
        "Q5 (60s): Recommendations. 2 immediate next steps + 1 safety-net statement (when to seek urgent care).",
    ]
    prompts: List[Tuple[int, str, str]] = [(0, stem, "stem")]
    for i, p in enumerate(probes, start=1):
        prompts.append((i, p, "probe"))
    return prompts


def build_case2_prompts(spec: ScenarioSpec) -> List[Tuple[int, str, str]]:
    stem = (
        "OSCE-style structured interview (Case 2: Treatment + Management)\n\n"
        "Role/setting: You are the physiotherapist planning and managing care. You are speaking to an examiner.\n"
        "Rules: Answer in order. Be specific to THIS client. Prioritize safety first.\n\n"
        f"Region: {spec.region}\n"
        f"Client: {spec.patient_seed}\n\n"
        "Answer format for each question:\n"
        "- Headline (≤10s)\n"
        "- Bullets (≤60s): top 3 items, then 1–2 details if time\n"
        "- Safety check (≤10s)\n"
    )
    probes = [
        "Q1 (90s): Treatment plan. Top 3 interventions + basic dosage/progression (how you’ll progress/regress).",
        "Q2 (60s): Goals + collaboration. 2 SMART goals + how you’ll align with client priorities/barriers.",
        "Q3 (60s): Safety + precautions. Top 2 precautions/contraindications + monitoring + what you’d do if worse.",
        "Q4 (60s): Reassessment. 2 outcomes you’ll track + when you’ll modify the plan + criteria to escalate/referral.",
        "Q5 (60s): Self-management + discharge. Home program (what/how often) + discharge criteria + safety-net.",
        "Q6 (45s): Collaboration/referral. 1–2 reasons to collaborate or refer + who/when.",
    ]
    prompts: List[Tuple[int, str, str]] = [(0, stem, "stem")]
    for i, p in enumerate(probes, start=1):
        prompts.append((i, p, "probe"))
    return prompts


def station_metadata_for_case_type(case_type: str) -> Dict:
    if case_type == "case1_assessment":
        return {
            "reading_seconds": 60,
            "time_limit_seconds": 8 * 60,
            "setting": "Outpatient physiotherapy clinic",
            "role_level": "Entry-to-practice physiotherapist (supervised)",
            "allowed_actions": [
                "ask.symptom_history",
                "ask.red_flags",
                "ask.pm_hx",
                "ask.meds_allergies",
                "obtain.consent",
                "communicate.teach_back",
                "exam.inspect",
                "exam.rom",
                "exam.neuro_screen",
                "exam.special_tests",
                "exam.functional_assessment",
                "investigation.request_basic",
                "interpret.results",
                "advise.safety_net",
            ],
            "probe_budget": 4,
            "exam_mode": {
                "no_backtracking": True,
                "allow_self_correction": True,
                "scoring_policy": "latest_statement_counts",
                "strict_actions": True,
                "max_fact_prefix_results": 10,
            },
        }
    # Case 2: treatment + management
    return {
        "reading_seconds": 60,
        "time_limit_seconds": 9 * 60,
        "setting": "Outpatient physiotherapy clinic",
        "role_level": "Entry-to-practice physiotherapist (supervised)",
        "allowed_actions": [
            "plan.treatment",
            "advise.self_management",
            "plan.reassessment_criteria",
            "advise.safety_net",
            "plan.escalate_or_refer",
            "obtain.consent",
            "communicate.teach_back",
        ],
        "probe_budget": 4,
        "exam_mode": {
            "no_backtracking": True,
            "allow_self_correction": True,
            "scoring_policy": "latest_statement_counts",
            "strict_actions": True,
            "max_fact_prefix_results": 10,
        },
    }


def upsert_case_metadata(conn: psycopg.Connection, *, case_id: str, metadata: Dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            update cases
            set reading_seconds = %s,
                time_limit_seconds = %s,
                setting = %s,
                role_level = %s,
                allowed_actions = %s,
                probe_budget = %s,
                exam_mode = %s,
                prompt_version = %s
            where id = %s
            """,
            (
                metadata["reading_seconds"],
                metadata["time_limit_seconds"],
                metadata["setting"],
                metadata["role_level"],
                Json(metadata["allowed_actions"]),
                metadata["probe_budget"],
                Json(metadata["exam_mode"]),
                "v2",
                case_id,
            ),
        )


def upsert_patient_profile(conn: psycopg.Connection, *, case_id: str, spec: ScenarioSpec) -> None:
    profile = {
        "chief_complaint": spec.title,
        "region": spec.region,
        "opening_statement": spec.patient_seed,
        "communication_style": "neutral",
        "health_literacy": {"preferred_explanation_style": "step_by_step", "teach_back_recommended": True},
        "emotional_tone": "neutral",
        "main_worry_prompt": "What worries you most about this problem?",
        "goals_prompt": "What activities are you most hoping to get back to?",
        "decision_preference": "shared",
    }
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into case_patient_profiles (case_id, profile)
            values (%s, %s)
            on conflict (case_id) do update
              set profile = excluded.profile
            """,
            (case_id, Json(profile)),
        )


def upsert_default_safety_expectations(conn: psycopg.Connection, *, case_id: str) -> None:
    # Keep rules small and generic; case-specific rules can be added later from structured extraction.
    rules = [
        ("ask.red_flags", "required", None, "early", 120, "major", ["physio_expertise"], "Screen red flags early."),
        ("obtain.consent", "required", None, "anytime", None, "major", ["professionalism", "communication"], "Obtain informed consent."),
        ("ask.allergies", "conditional_required", {"if": "recommends_meds_or_modalities"}, "anytime", None, "minor", ["professionalism"], "Ask about allergies if recommending meds/modalities."),
        ("advise.safety_net", "required", None, "before_disposition", None, "major", ["professionalism", "communication"], "Provide safety-net advice."),
    ]
    with conn.cursor() as cur:
        for (rule_key, rule_type, cond, phase, deadline_s, severity, domains, desc) in rules:
            cur.execute(
                """
                insert into case_safety_expectations
                  (case_id, action_key, rule_type, trigger_condition, time_window, time_limit_seconds, severity_if_missed, domain_tags, feedback_template)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (case_id, action_key, rule_type) do update
                  set trigger_condition = excluded.trigger_condition,
                      time_window = excluded.time_window,
                      time_limit_seconds = excluded.time_limit_seconds,
                      severity_if_missed = excluded.severity_if_missed,
                      domain_tags = excluded.domain_tags,
                      feedback_template = excluded.feedback_template
                """,
                (
                    case_id,
                    rule_key,
                    rule_type,
                    Json(cond) if cond else None,
                    phase,
                    deadline_s,
                    severity,
                    Json(domains),
                    desc,
                ),
            )


def build_expected_elements(spec: ScenarioSpec) -> List[Tuple[str, str]]:
    # These are generalized “must/should” expectations; rubric mapping happens separately.
    return [
        ("must", "Screens for key red flags and contraindications relevant to the presentation."),
        ("must", "Obtains and documents informed consent; explains risks/benefits and confirms understanding."),
        ("must", "Collects focused subjective history (mechanism, aggravating/easing, irritability, 24h pattern, function, goals)."),
        ("should", "Selects objective tests/measures appropriate to the region and suspected condition; justifies test selection."),
        ("should", "States a working diagnosis/differential and identifies what data would confirm/refute it."),
        ("should", "Proposes an evidence-informed plan including education and graded activity/exercise."),
        ("should", "Communicates clearly, uses client-centred language, and checks understanding (teach-back)."),
        ("should", "Plans reassessment metrics and criteria to progress/modify/discharge."),
        ("nice", "Considers psychosocial factors and barriers; tailors plan accordingly."),
        ("nice", "Identifies when to collaborate or refer to another provider and provides safety-net advice."),
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate paired OSCE cases from Dutton chunks and store them in Postgres.")
    ap.add_argument("--source-id", default=DEFAULT_DUTTON_SOURCE_ID, help="sources.id for the Dutton PDF")
    ap.add_argument("--max-scenarios", type=int, default=0, help="How many scenario specs to generate (0 = all)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--status", default="draft", choices=["draft", "published"])
    args = ap.parse_args()

    random.seed(args.seed)
    specs = SCENARIOS[:]
    if args.max_scenarios and args.max_scenarios > 0:
        specs = specs[: args.max_scenarios]

    with psycopg.connect(require_database_url(), row_factory=dict_row) as conn:
        conn.autocommit = True

        domain_ids = get_oce_rubric_domain_ids(conn, rubric_name="OCE Domains")
        # Pre-pick a handful of criteria IDs per domain to attach expected elements (best-effort).
        criteria_pool: Dict[str, List[str]] = {
            k: get_some_criteria_ids(conn, rubric_domain_id=v, limit=10) for k, v in domain_ids.items()
        }

        created = 0
        for spec in specs:
            # Use snippets only to ensure the topic exists in the text (sanity check)
            snippets = fetch_snippets(conn, source_id=args.source_id, keywords=spec.keywords, max_snippets=2)
            if not snippets:
                # If the book text extraction doesn’t contain the keywords, skip (avoid hallucinating content).
                continue

            base_title = f"Dutton OSCE: {spec.title}"

            # Case 1: assessment
            case1_title = f"{base_title} (Case 1: Assessment)"
            case1_id = ensure_case(
                conn,
                title=case1_title,
                case_type="case1_assessment",
                source_id=args.source_id,
                status=args.status,
            )
            insert_prompts(conn, case_id=case1_id, prompts=build_case1_prompts(spec))
            upsert_case_metadata(conn, case_id=case1_id, metadata=station_metadata_for_case_type("case1_assessment"))
            upsert_patient_profile(conn, case_id=case1_id, spec=spec)
            upsert_default_safety_expectations(conn, case_id=case1_id)

            # Case 2: treatment/management
            case2_title = f"{base_title} (Case 2: Treatment + Management)"
            case2_id = ensure_case(
                conn,
                title=case2_title,
                case_type="case2_treatment_management",
                source_id=args.source_id,
                status=args.status,
            )
            insert_prompts(conn, case_id=case2_id, prompts=build_case2_prompts(spec))
            upsert_case_metadata(
                conn, case_id=case2_id, metadata=station_metadata_for_case_type("case2_treatment_management")
            )
            upsert_patient_profile(conn, case_id=case2_id, spec=spec)
            upsert_default_safety_expectations(conn, case_id=case2_id)

            # Expected elements -> attach to a small set of Physio Expertise + Communication + Professionalism criteria
            exp = build_expected_elements(spec)
            pe = criteria_pool.get("physio_expertise", [])
            comm = criteria_pool.get("communication", [])
            prof = criteria_pool.get("professionalism", [])

            mapped: List[Tuple[str, str, Optional[str]]] = []
            for idx, (importance, text) in enumerate(exp):
                # simple round-robin mapping for traceability; evaluator can still score at domain-level
                criterion_id: Optional[str] = None
                if idx % 3 == 0 and pe:
                    criterion_id = pe[idx % len(pe)]
                elif idx % 3 == 1 and comm:
                    criterion_id = comm[idx % len(comm)]
                elif idx % 3 == 2 and prof:
                    criterion_id = prof[idx % len(prof)]
                mapped.append((importance, text, criterion_id))

            # Insert expected elements only if the case doesn't already have any
            with conn.cursor() as cur:
                cur.execute("select 1 from case_expected_elements where case_id = %s limit 1", (case1_id,))
                if cur.fetchone() is None:
                    insert_expected_elements(conn, case_id=case1_id, elements=mapped)
                cur.execute("select 1 from case_expected_elements where case_id = %s limit 1", (case2_id,))
                if cur.fetchone() is None:
                    insert_expected_elements(conn, case_id=case2_id, elements=mapped)

            # Store a small extraction note in extractions by inserting a synthetic record is out of scope.
            created += 2

        print(f"Created {created} cases (paired Case1/Case2) from Dutton topics.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

