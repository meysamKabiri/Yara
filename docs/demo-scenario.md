# Yara MVP Demo Scenario

## Demo goal

Use this scenario to validate that the current MVP can create a project, process Persian natural input, confirm records, calculate project totals, correct or void confirmed records, export CSV files, and remain usable on mobile.

This demo pack is for validation only. It should not change extraction logic or financial business rules.

## Project

Suggested project name:

```text
ویلا دماوند - نسخه دمو
```

## Natural inputs

Submit and confirm these inputs one by one:

```text
میثم کبیری کارفرمای پروژه است
```

```text
هادی پور فروشنده پروژه است
```

```text
مش رحیم کارگر پروژه است
```

```text
دستمزد روزانه مش رحیم ۱۲۰۰۰۰۰ تومان است
```

```text
میثم کبیری ۱۰۰ میلیون تومان پرداخت کرد
```

```text
از هادی پور ۲۰ میلیون تومان سیم خریداری و پرداخت شد
```

```text
از آهنچی ۵۰ میلیون تومان آهن خریداری شد ولی هنوز پرداخت نشده
```

```text
مش رحیم هفته قبل ۴ روز و نصفی کار کرد
```

```text
به مش رحیم ۲ میلیون تومان پرداخت شد
```

```text
کارفرما گفت رنگ در تغییر کند
```

## Expected results

- Client money in: 100,000,000
- Paid out:
  - 20,000,000 vendor payment
  - 2,000,000 worker payment
  - total paid out = 22,000,000
- Labor cost:
  - 4.5 x 1,200,000 = 5,400,000
- Open vendor payable:
  - آهنچی = 50,000,000
- Worker remaining:
  - labor cost 5,400,000 - paid 2,000,000 = 3,400,000
- Net cash:
  - 100,000,000 - 22,000,000 = 78,000,000
- The note appears in notes:
  - کارفرما گفت رنگ در تغییر کند

Note: the app report's approximate balance subtracts open payables too. The demo net cash above is only cash in minus paid-out cash.

## Correction and void validation

- Correct هادی پور payment from 20M to 25M.
  - Expected paid out = 27M.
  - Expected net cash = 73M.
- Void مش رحیم 2M payment.
  - Expected paid out decreases by 2M.
  - Expected worker remaining increases.
- Correct مش رحیم work log from 4.5 days to 5 days.
  - Expected labor cost = 6M.
- Void آهنچی payable.
  - Expected open vendor payable decreases by 50M.

## Report and export validation

- Reports exclude voided records.
- CSV exports exclude voided records by default.
- Corrected records appear with corrected values.
- Validate these exports:
  - Summary CSV
  - Payments CSV
  - People CSV
  - Work logs CSV
  - Payables CSV
  - Notes CSV

## Mobile validation checklist

- 390px viewport
- AI overlay fits
- review modal actions visible
- correction/void modal footer visible
- no horizontal overflow
- bottom navigation does not cover actions

## Optional seed script

To create confirmed demo data directly in the development database:

```bash
cd backend
python scripts/seed_demo_project.py
```

The script is dev-only and creates a new timestamped demo project each time.
