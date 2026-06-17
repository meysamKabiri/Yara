import random
from typing import Any

DAILY_WORKERS = ["مش رحیم", "مش سهراب", "استاد کریم"]
SKILLED_WORKERS = ["نادری جوشکار", "برقکار کیانی", "حسن سنگ‌کار"]
VENDORS = ["هادی‌پور سیم", "فروشگاه رنگ نوری", "آهن فروشی امیری"]


def generate_random_scenario(seed: int = 1) -> dict[str, Any]:
    rng = random.Random(seed)
    daily_worker = rng.choice(DAILY_WORKERS)
    skilled_worker = rng.choice(SKILLED_WORKERS)
    vendor = rng.choice(VENDORS)
    meters = rng.choice([10, 20, 35, 40])
    invoice_millions = rng.choice([5, 12, 34])

    return {
        "name": f"generated_{seed}",
        "project_name": f"Generated Sandbox {seed}",
        "setup": [
            {
                "text": "کارفرمای پروژه میثم کبیری است",
                "graph": {
                    "intent": "SETUP",
                    "entities": [{"type": "CLIENT", "name": "میثم کبیری"}],
                    "confidence": 1,
                },
            },
            {
                "text": f"{daily_worker} و {skilled_worker} تو پروژه هستند",
                "graph": {
                    "intent": "SETUP",
                    "entities": [
                        {"type": "WORKER", "name": daily_worker},
                        {"type": "WORKER", "name": skilled_worker},
                    ],
                    "confidence": 1,
                },
            },
            {
                "text": f"فروشنده پروژه {vendor} است",
                "graph": {
                    "intent": "SETUP",
                    "entities": [{"type": "VENDOR", "name": vendor}],
                    "confidence": 1,
                },
            },
        ],
        "messages": [
            {
                "text": f"{daily_worker} امروز کار کرد",
                "graph": {"intent": "WORK", "entity": daily_worker, "action": "INCREMENT"},
            },
            {
                "text": f"{skilled_worker} {meters} متر کار کرد",
                "graph": {"intent": "WORK", "entity": skilled_worker, "action": "INCREMENT"},
            },
            {
                "text": f"{vendor} فاکتور {invoice_millions} میلیونی داد",
                "graph": {"intent": "INVOICE", "entity": vendor, "action": "INVOICE"},
            },
        ],
    }
