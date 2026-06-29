from app.services.input_normalizer import normalize_user_input
from app.services.prompts.llm_v2_prompt import build_llm_v2_prompt
from tests.natural_input_helpers import natural_input_interpretation


def _first_entity(text: str) -> dict:
    normalized = normalize_user_input(text)
    assert normalized["entities"]
    return normalized["entities"][0]


def test_role_statement_extracts_clean_client_name() -> None:
    normalized = normalize_user_input("میثم کبیری کارفر مای پروژه")
    entity = normalized["entities"][0]

    assert entity["name"] == "میثم کبیری"
    assert entity["role"] == "CLIENT"
    assert normalized["clean_text"] == "میثم کبیری کارفرما پروژه"
    assert ":" not in entity["name"]


def test_worker_statement_excludes_project_or_role_tail() -> None:
    entity = _first_entity("مش رحیم کارگر ساره")

    assert entity["name"] == "مش رحیم"
    assert entity["role"] == "WORKER"
    assert "کارگر" not in entity["name"]
    assert ":" not in entity["name"]


def test_role_before_name_removes_daily_worker_modifiers() -> None:
    entity = _first_entity("کارگر روز مزد مش رحیم")

    assert entity["name"] == "مش رحیم"
    assert entity["role"] == "DAILY_WORKER"
    assert "کارگر" not in entity["name"]
    assert "روز مزد" not in entity["name"]


def test_skilled_role_before_name_extracts_clean_name() -> None:
    tile_worker = _first_entity("کاشی کار ریاحی")
    electrician = _first_entity("برق کار علی محمدی")

    assert tile_worker["name"] == "ریاحی"
    assert tile_worker["role"] == "SKILLED_WORKER"
    assert electrician["name"] == "علی محمدی"
    assert electrician["role"] == "SKILLED_WORKER"


def test_contact_statement_extracts_name_and_phone_separately() -> None:
    normalized = normalize_user_input("شماره تماس میثم: 0913284")
    entity = normalized["entities"][0]

    assert entity["name"] == "میثم"
    assert normalized["financials"]["phone"] == "0913284"
    assert normalized["facts"][0]["type"] == "PHONE"
    assert ":" not in entity["name"]


def test_daily_rate_statement_extracts_name_and_amount_separately() -> None:
    normalized = normalize_user_input("دستمزد مش رحیم : 1200000")
    entity = normalized["entities"][0]

    assert entity["name"] == "مش رحیم"
    assert normalized["financials"]["amount"] == 1200000
    assert any(fact["type"] == "AMOUNT" for fact in normalized["facts"])
    assert ":" not in entity["name"]


def test_token_normalizer_corrects_controlled_role_typos() -> None:
    assert normalize_user_input("میثم گارفرما")["clean_text"] == "میثم کارفرما"
    assert normalize_user_input("میثم صاحاب پروژه")["clean_text"] == "میثم صاحب پروژه"


def test_llm_prompt_uses_structured_input_not_raw_sentence() -> None:
    raw_text = "شماره تماس میثم: 0913284"
    prompt, domain = build_llm_v2_prompt(raw_text, project_id=1)

    assert domain == "setup"
    assert "Normalized input JSON:" in prompt
    assert '"name":"میثم"' in prompt
    assert '"phone":"0913284"' in prompt
    assert f"Note: {raw_text}" not in prompt


def test_pipeline_role_fast_path_uses_clean_normalized_name(client) -> None:
    project = client.post("/projects", json={"name": "normalizer role"}).json()

    interpretation = natural_input_interpretation(
        client,
        project["id"],
        "مش رحیم کارگر ساره",
    )

    entity = interpretation["extracted_entities"][0]
    assert entity["name"] == "مش رحیم"
    assert entity["project_role"] == "DAILY_WORKER"
    assert ":" not in entity["name"]


def test_pipeline_role_before_name_uses_clean_normalized_name(client) -> None:
    project = client.post("/projects", json={"name": "normalizer role before name"}).json()

    interpretation = natural_input_interpretation(
        client,
        project["id"],
        "کارگر روز مزد مش رحیم",
    )

    entity = interpretation["extracted_entities"][0]
    assert entity["name"] == "مش رحیم"
    assert entity["project_role"] == "DAILY_WORKER"
    assert "روز مزد" not in entity["name"]


def test_pipeline_contact_fast_path_uses_clean_normalized_name(client) -> None:
    project = client.post("/projects", json={"name": "normalizer contact"}).json()

    interpretation = natural_input_interpretation(
        client,
        project["id"],
        "شماره تماس میثم: 0913284",
    )

    entity = interpretation["extracted_entities"][0]
    assert entity["name"] == "میثم"
    assert entity["phone"] == "0913284"
    assert ":" not in entity["name"]
