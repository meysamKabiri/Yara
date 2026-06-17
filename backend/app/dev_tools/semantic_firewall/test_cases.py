from typing import Any

SEMANTIC_TEST_CASES: list[dict[str, Any]] = [
    {
        "name": "daily work implicit",
        "input": "مش رحیم امروز کار کرد",
        "expected_event_type": "WORK_EVENT",
        "expected_entity": "مش رحیم",
        "context_entities": ["مش رحیم"],
    },
    {
        "name": "skilled welding progress",
        "input": "نادری جوشکار ۲۰ متر جوش داد",
        "expected_event_type": "WORK_EVENT",
        "expected_entity": "نادری جوشکار",
        "context_entities": ["نادری جوشکار"],
    },
    {
        "name": "informal million payment typo",
        "input": "۱۰۰ ملیون دادم",
        "expected_event_type": "FINANCIAL_EVENT",
        "expected_entity": None,
        "context_entities": [],
    },
    {
        "name": "settlement financial meaning",
        "input": "تسویه شد",
        "expected_event_type": "FINANCIAL_EVENT",
        "expected_entity": None,
        "context_entities": [],
    },
    {
        "name": "known client settlement",
        "input": "کارفرما گفت تسویه شد",
        "expected_event_type": "FINANCIAL_EVENT",
        "expected_entity": "میثم کبیری",
        "context_entities": ["میثم کبیری"],
    },
    {
        "name": "vendor purchase informal spacing",
        "input": "خرید کردم از هادی پور",
        "expected_event_type": "FINANCIAL_EVENT",
        "expected_entity": "هادی پور",
        "context_entities": ["هادی پور"],
    },
    {
        "name": "client setup",
        "input": "کارفرما میثم کبیری است",
        "expected_event_type": "SETUP_EVENT",
        "expected_entity": None,
        "context_entities": [],
    },
    {
        "name": "ambiguous reminder remains note",
        "input": "یادم باشد بعدا بررسی کنم",
        "expected_event_type": "NOTE_EVENT",
        "expected_entity": None,
        "context_entities": [],
    },
    {
        "name": "known entity today context blocked from note",
        "input": "رحیم امروز",
        "expected_event_type": "WORK_EVENT",
        "expected_entity": "مش رحیم",
        "context_entities": ["مش رحیم"],
    },
]
