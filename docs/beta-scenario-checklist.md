# Beta Scenario Checklist

## Purpose

This checklist verifies Yara's real end-to-end user journey before sharing the app with 3-4 beta testers.

The goal is to confirm that a non-developer user can:

- sign up and create a project
- enter natural Persian construction/project text
- understand the pending interpretation card
- edit uncertain fields before confirming
- confirm only when the card is correct
- see profiles, work, and financial totals update safely after confirmation

This plan does not change AI behavior, financial execution, normalizer rules, or prompts. It is a manual beta-readiness checklist only.

## Pre-Test Setup

Use the existing project docs and scripts where available. Do not invent a new deployment flow for this checklist.

Suggested references:

- `docs/dev-docker.md`
- `docs/deployment.md`
- `README.md`

Before testing:

- [ ] Start Postgres.
- [ ] Start Redis.
- [ ] Start Ollama.
- [ ] Start the backend.
- [ ] Start the frontend.
- [ ] Run database migrations using the existing migration command/script.
- [ ] Confirm backend health endpoint is reachable.
- [ ] Confirm the frontend loads in the browser.

Command placeholders:

```bash
# Backend/frontend startup:
# Use existing commands from README.md or docs/dev-docker.md

# Migrations:
# Use the existing Alembic or app migration command documented for the project
```

## Test User Setup

- [ ] Open the frontend.
- [ ] Sign up with a fresh beta test email.
- [ ] Log out.
- [ ] Log back in with the same user.
- [ ] Confirm old data from other users is not visible.

Test user:

- Email:
- Password:
- Tester name:
- Date:

## Project Setup

- [ ] Create a fresh project named `ویلا دماوند تستی`.
- [ ] Open the project detail screen.
- [ ] Confirm initial people, payments, work logs, reports, and pending cards are empty or zero.

Project:

- Project name: `ویلا دماوند تستی`
- Project ID:
- Tester:
- Date:

## Beta Safety UX Checks

- [ ] All financial amounts show `تومان`.
- [ ] Financial impact text clearly says whether cash balance increases or decreases.
- [ ] Low-confidence or uncertain cards show `یارا از این برداشت مطمئن نیست. لطفاً قبل از ثبت بررسی کنید.`
- [ ] Multi-action input shows `این متن ممکن است شامل چند عملیات باشد. برای دقت بیشتر، هر عملیات را جداگانه وارد کنید.`
- [ ] Loading state says `یارا در حال بررسی متن شماست...`
- [ ] No contractor-facing card uses confusing technical terms like `pending`.

## Core Scenario Checklist

### Scenario 1 — Create Project Client

Input:
`میثم کبیری کارفرمای پروژه`

Expected card:
- Domain: SETUP
- Name: میثم کبیری
- Role/action: CLIENT / create or update project client
- Amount/phone/account: none
- Editable fields: name, role/profile fields if shown

After confirm:
- Expected saved record: میثم کبیری exists as project client.
- Expected totals/profile impact: profile list updates; financial totals do not change.

Must NOT happen:
- Name must not include `کارفرمای پروژه`.
- No payment, invoice, or work log should be created.

Result:
- [ ] Pass
- [ ] Fail
- Actual result:

Notes:

### Scenario 2 — Create Daily Worker From Role After Name

Input:
`مش رحیم کارگر روزمزد`

Expected card:
- Domain: SETUP
- Name: مش رحیم
- Role/action: DAILY_WORKER
- Amount/phone/account: none
- Editable fields: name, role, role detail

After confirm:
- Expected saved record: مش رحیم exists as daily worker.
- Expected totals/profile impact: worker profile updates; financial totals do not change.

Must NOT happen:
- Name must not include role words such as `کارگر` or `روزمزد`.
- No payment should be created.

Result:
- [ ] Pass
- [ ] Fail
- Actual result:

Notes:

### Scenario 3 — Create Daily Worker From Role Before Name

Input:
`کارگر روز مزد مش رحیم`

Expected card:
- Domain: SETUP
- Name: مش رحیم
- Role/action: DAILY_WORKER
- Amount/phone/account: none
- Editable fields: name, role, role detail

After confirm:
- Expected saved record: مش رحیم exists as daily worker.
- Expected totals/profile impact: worker profile updates; financial totals do not change.

Must NOT happen:
- Card should not show a corrupted name.
- Name must not include `کارگر` or `روز مزد`.

Result:
- [ ] Pass
- [ ] Fail
- Actual result:

Notes:

### Scenario 4 — Create Skilled Worker With Spaced Role

Input:
`کاشی کار ریاحی`

Expected card:
- Domain: SETUP
- Name: ریاحی
- Role/action: SKILLED_WORKER
- Amount/phone/account: none
- Editable fields: name, role, role detail

After confirm:
- Expected saved record: ریاحی exists as skilled worker.
- Expected totals/profile impact: worker profile updates; financial totals do not change.

Must NOT happen:
- Name must not include `کاشی کار`.
- No financial record should be created.

Result:
- [ ] Pass
- [ ] Fail
- Actual result:

Notes:

### Scenario 5 — Create Skilled Worker With Compact Role

Input:
`کاشیکار ریاحی`

Expected card:
- Domain: SETUP
- Name: ریاحی
- Role/action: SKILLED_WORKER
- Amount/phone/account: none
- Editable fields: name, role, role detail

After confirm:
- Expected saved record: ریاحی exists as skilled worker.
- Expected totals/profile impact: worker profile updates; financial totals do not change.

Must NOT happen:
- Name must not be corrupted.
- Name must not include `کاشیکار`.

Result:
- [ ] Pass
- [ ] Fail
- Actual result:

Notes:

### Scenario 6 — Update Phone Number

Input:
`شماره تماس میثم: 09132842675`

Expected card:
- Domain: CONTACT
- Name: میثم
- Role/action: UPDATE_PHONE
- Amount/phone/account: phone = 09132842675
- Editable fields: name/person selection, phone

After confirm:
- Expected saved record: میثم profile has phone number 09132842675.
- Expected totals/profile impact: profile updates; financial totals do not change.

Must NOT happen:
- Role/payment fields should not be shown unnecessarily.
- No payment should be created from the phone number.

Result:
- [ ] Pass
- [ ] Fail
- Actual result:

Notes:

### Scenario 7 — Update Account Number

Input:
`شماره حساب میثم : 664334566666666`

Expected card:
- Domain: ACCOUNT
- Name: میثم
- Role/action: UPDATE_ACCOUNT
- Amount/phone/account: account number = 664334566666666
- Editable fields: name/person selection, account number

After confirm:
- Expected saved record: میثم profile has account number 664334566666666.
- Expected totals/profile impact: profile updates; financial totals do not change.

Must NOT happen:
- Role/payment fields should not be shown unnecessarily.
- Account number should not be treated as payment amount.

Result:
- [ ] Pass
- [ ] Fail
- Actual result:

Notes:

### Scenario 8 — Incoming Client Payment

Input:
`از میثم ۵۰ میلیون گرفتم`

Expected card:
- Domain: FINANCIAL
- Name: میثم
- Role/action: incoming payment / client-like payer
- Amount/phone/account: amount = 50000000, direction = INCOMING
- Editable fields: person, amount, direction/payment details if shown

After confirm:
- Expected saved record: incoming payment from میثم for 50000000.
- Expected totals/profile impact: project cash/balance increases only after confirm.

Must NOT happen:
- Pending card must not affect totals before confirmation.
- Direction must not be OUTGOING.

Result:
- [ ] Pass
- [ ] Fail
- Actual result:

Notes:

### Scenario 9 — Outgoing Worker Payment

Input:
`به مش رحیم ۲ میلیون دادم`

Expected card:
- Domain: FINANCIAL
- Name: مش رحیم
- Role/action: outgoing payment
- Amount/phone/account: amount = 2000000, direction = OUTGOING
- Editable fields: person, amount, direction/payment details if shown

After confirm:
- Expected saved record: outgoing payment to مش رحیم for 2000000.
- Expected totals/profile impact: project cash/balance decreases only after confirm.

Must NOT happen:
- Pending card must not affect totals before confirmation.
- Direction must not be INCOMING.

Result:
- [ ] Pass
- [ ] Fail
- Actual result:

Notes:

### Scenario 10 — Purchase Paid To Vendor

Input:
`از هادی پور 25 میلیون سیم خریدم و پرداخت کردم`

Expected card:
- Domain: FINANCIAL
- Name: هادی پور
- Role/action: VENDOR or vendor-like party / purchase paid
- Amount/phone/account: amount = 25000000, direction = OUTGOING
- Editable fields: vendor/person, amount, payment details if shown

After confirm:
- Expected saved record: purchase/payment record for هادی پور.
- Expected totals/profile impact: project cash/balance decreases only after confirm.

Must NOT happen:
- Purchase should not be treated as incoming project money.
- Pending card must not affect totals before confirmation.

Result:
- [ ] Pass
- [ ] Fail
- Actual result:

Notes:

### Scenario 11 — Daily Wage Profile Update

Input:
`دستمزد روزانه مش رحیم : 1200000`

Expected card:
- Domain: SETUP or worker profile update, depending current implementation
- Name: مش رحیم
- Role/action: daily wage/profile update
- Amount/phone/account: daily wage = 1200000
- Editable fields: name/person selection, daily wage

After confirm:
- Expected saved record: مش رحیم profile daily wage is 1200000 if supported.
- Expected totals/profile impact: profile updates; financial totals do not change.

Must NOT happen:
- Must not create a payment unless user is explicitly confirming a financial payment action.
- Wage amount should not immediately affect cash balance.

Result:
- [ ] Pass
- [ ] Fail
- Actual result:

Notes:

### Scenario 12 — Worker Worked Today

Input:
`مش رحیم امروز کار کرد`

Expected card:
- Domain: WORK if currently supported
- Name: مش رحیم
- Role/action: work log or safe NOTE/OTHER if not supported
- Amount/phone/account: none
- Editable fields: worker/person, work details if WORK card appears

After confirm:
- Expected saved record: work log is created if supported.
- Expected totals/profile impact: work history updates if supported; otherwise no financial/profile side effect.

Must NOT happen:
- App must not crash.
- If unsupported, it should produce safe NOTE/OTHER behavior rather than a corrupted financial record.

Result:
- [ ] Pass
- [ ] Fail
- Actual result:

Notes:

### Scenario 13 — Edit Name Before Confirm

Input:
`مش رحیم کارگر روزمزد`

Manual action:
- Edit name to `مش رحیم اصلاح شده`.
- Confirm.

Expected card:
- Domain: SETUP
- Name: initially مش رحیم, then edited to مش رحیم اصلاح شده
- Role/action: DAILY_WORKER
- Amount/phone/account: none
- Editable fields: name, role/profile fields if shown

After confirm:
- Expected saved record: final saved record uses edited name.
- Expected totals/profile impact: profile updates; financial totals do not change.
- Feedback capture should record the correction.

Must NOT happen:
- Original unedited name should not be saved as the final confirmed profile.
- No accidental duplicate profile should be created if entity resolution handles it.

Result:
- [ ] Pass
- [ ] Fail
- Actual result:

Notes:

### Scenario 14 — Edit Amount Before Confirm

Input:
`از میثم ۵۰ میلیون گرفتم`

Manual action:
- Change amount before confirm.
- Confirm.

Expected card:
- Domain: FINANCIAL
- Name: میثم
- Role/action: incoming payment
- Amount/phone/account: amount initially 50000000, then edited amount
- Editable fields: amount, person, direction/payment details if shown

After confirm:
- Expected saved record: confirmed financial record uses edited amount.
- Expected totals/profile impact: project totals use edited amount only after confirm.
- Feedback capture should record WRONG_AMOUNT.

Must NOT happen:
- Original pending interpretation must not affect totals before confirm.
- Confirmed totals must not use the old amount.

Result:
- [ ] Pass
- [ ] Fail
- Actual result:

Notes:

### Scenario 15 — Corrupted Client Role Spacing

Input:
`کارفر مای پروژه میثم کبیری`

Expected card:
- Domain: safe OTHER/SETUP if ambiguous
- Name: should be clean if a name is extracted
- Role/action: safest classification available
- Amount/phone/account: none
- Editable fields: enough fields to correct safely

After confirm:
- Expected saved record: only confirmed user-corrected data is saved.
- Expected totals/profile impact: profile only if user confirms setup/profile action.

Must NOT happen:
- Name should not become `کارفر مای پروژه`.
- App must not create a corrupted person automatically.

Result:
- [ ] Pass
- [ ] Fail
- Actual result:

Notes:

### Scenario 16 — Separator Between Role And Name

Input:
`کارگر روز مزد: مش رحیم`

Expected card:
- Domain: SETUP
- Name: مش رحیم
- Role/action: DAILY_WORKER
- Amount/phone/account: none
- Editable fields: name, role, role detail

After confirm:
- Expected saved record: مش رحیم exists as daily worker.
- Expected totals/profile impact: profile updates; financial totals do not change.

Must NOT happen:
- Separator must not corrupt the name.
- Name must not include `کارگر روز مزد`.

Result:
- [ ] Pass
- [ ] Fail
- Actual result:

Notes:

### Scenario 17 — Only Phone Number

Input:
`09132842675`

Expected card:
- Domain: safe CONTACT/OTHER/NOTE behavior
- Name: none unless user supplies one
- Role/action: no random profile creation
- Amount/phone/account: phone may be recognized, but should require a person/name before useful profile update
- Editable fields: if card appears, fields should make uncertainty clear

After confirm:
- Expected saved record: no random person is created.
- Expected totals/profile impact: financial totals do not change.

Must NOT happen:
- App must not crash.
- Phone number must not become a payment amount.
- App must not create a random person.

Result:
- [ ] Pass
- [ ] Fail
- Actual result:

Notes:

### Scenario 18 — Empty Input

Input:
``

Expected card:
- Domain: none, validation error, or safe no-op
- Name: none
- Role/action: none
- Amount/phone/account: none
- Editable fields: none

After confirm:
- Expected saved record: none
- Expected totals/profile impact: no change

Must NOT happen:
- App must not crash.
- No pending corrupted card should be created.
- No profile, payment, invoice, work log, or note should be created from empty input.

Result:
- [ ] Pass
- [ ] Fail
- Actual result:

Notes:

## Cross-Scenario Checks

Run these checks throughout the scenarios:

- [ ] Pending interpretation cards are understandable before confirmation.
- [ ] Pending records do not change totals before confirmation.
- [ ] Confirmed records update only the intended profile, work, or financial data.
- [ ] User edits before confirmation are reflected in final saved data.
- [ ] Feedback is captured when the user edits/corrects an interpretation.
- [ ] No role words appear inside saved names.
- [ ] Contact/account cards do not show unrelated financial fields.
- [ ] Financial cards clearly show direction and amount.
- [ ] The app remains usable after invalid or ambiguous input.

## Pass/Fail Notes

Use this section for tester observations that do not fit a single scenario.

- Tester:
- Browser/device:
- Date:
- Actual result:

Notes:

## Known Beta Limitations

Known limitations for beta:

- No voice input.
- No OCR.
- No mobile app yet.
- No multi-user project sharing.
- No automatic learning updates.
- Complex multi-action sentences may need manual correction.
- The system may ask the user to confirm or edit uncertain cards.

## Final Beta Readiness Checklist

- [ ] User can sign up/login.
- [ ] User can create project.
- [ ] Natural input creates understandable pending card.
- [ ] User can edit before confirm.
- [ ] Confirmed records update correct data.
- [ ] Pending records do not affect totals.
- [ ] Feedback is captured when edited.
- [ ] No corrupted names appear.
- [ ] No role words appear inside names.
- [ ] Contact/account cards do not show unrelated financial fields.
- [ ] Financial cards clearly show direction and amount.
- [ ] App does not crash on empty/invalid input.
- [ ] Tester can complete all core scenarios without developer help.
- [ ] Remaining failures are documented and triaged before beta release.
