from typing import Any

VILLA_PROJECT_BASIC: dict[str, Any] = {
    "name": "villa_project_basic",
    "project_name": "Villa Project",
    "setup": [
        {
            "text": "کارفرمای پروژه میثم کبیری است",
            "graph": {
                "intent": "SETUP",
                "entities": [
                    {
                        "type": "CLIENT",
                        "name": "میثم کبیری",
                        "phone": None,
                        "account_number": None,
                        "role_detail": None,
                    }
                ],
                "confidence": 1,
            },
        },
        {
            "text": "کارگرها مش رحیم و مش سهراب هستند",
            "graph": {
                "intent": "SETUP",
                "entities": [
                    {"type": "WORKER", "name": "مش رحیم", "role_detail": "daily worker"},
                    {"type": "WORKER", "name": "مش سهراب", "role_detail": "daily worker"},
                ],
                "confidence": 1,
            },
        },
        {
            "text": "نادری جوشکار و برقکار کیانی هم تو پروژه هستند",
            "graph": {
                "intent": "SETUP",
                "entities": [
                    {"type": "WORKER", "name": "نادری جوشکار", "role_detail": "welder"},
                    {"type": "WORKER", "name": "برقکار کیانی", "role_detail": "electrician"},
                ],
                "confidence": 1,
            },
        },
        {
            "text": "فروشنده سیم هادی‌پور سیم است",
            "graph": {
                "intent": "SETUP",
                "entities": [
                    {"type": "VENDOR", "name": "هادی‌پور سیم", "role_detail": "wire supplier"},
                ],
                "confidence": 1,
            },
        },
    ],
    "messages": [
        {
            "text": "مش رحیم امروز کار کرد",
            "graph": {
                "intent": "WORK",
                "entity": "مش رحیم",
                "action": "INCREMENT",
                "confidence": 1,
            },
        },
        {
            "text": "مش رحیم امروز کار کرد",
            "graph": {
                "intent": "WORK",
                "entity": "مش رحیم",
                "action": "INCREMENT",
                "confidence": 1,
            },
        },
        {
            "text": "نادری جوشکار ۲۰ متر جوش داد",
            "graph": {
                "intent": "WORK",
                "entity": "نادری جوشکار",
                "action": "INCREMENT",
                "confidence": 1,
            },
        },
        {
            "text": "۱۰۰ میلیون دادم به نادری جوشکار",
            "graph": {
                "intent": "PAYMENT",
                "entity": "نادری جوشکار",
                "action": "PAYMENT",
                "confidence": 1,
            },
        },
        {
            "text": "از هادی‌پور سیم ۵ میلیون خرید کردم",
            "graph": {
                "intent": "INVOICE",
                "entity": "هادی‌پور سیم",
                "action": "INVOICE",
                "confidence": 1,
            },
        },
        {
            "text": "کارفرما گفت تسویه شد",
            "graph": {"intent": "NOTE", "entity": "میثم کبیری", "action": "SET", "confidence": 0.6},
        },
    ],
}

SCENARIOS = {VILLA_PROJECT_BASIC["name"]: VILLA_PROJECT_BASIC}


def get_scenario(name: str) -> dict[str, Any]:
    return SCENARIOS[name]
