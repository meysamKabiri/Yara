export type JalaliDateParts = {
  year: number;
  month: number;
  day: number;
};

export type ReportFilterKey = "week" | "month" | "year" | "all";

const GREGORIAN_MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
const JALALI_MONTH_DAYS = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29];

function div(a: number, b: number): number {
  return Math.trunc(a / b);
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

export function isoDate(value: Date): string {
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`;
}

export function parseIsoDate(value: string): { year: number; month: number; day: number } | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (month < 1 || month > 12 || day < 1 || day > 31) return null;
  return { year, month, day };
}

export function toJalali(gy: number, gm: number, gd: number): JalaliDateParts {
  let gregorianYear = gy - 1600;
  let gregorianMonth = gm - 1;
  let gregorianDay = gd - 1;

  let dayNumber = 365 * gregorianYear + div(gregorianYear + 3, 4) - div(gregorianYear + 99, 100) + div(gregorianYear + 399, 400);
  for (let i = 0; i < gregorianMonth; i += 1) dayNumber += GREGORIAN_MONTH_DAYS[i];
  if (gregorianMonth > 1 && ((gy % 4 === 0 && gy % 100 !== 0) || gy % 400 === 0)) dayNumber += 1;
  dayNumber += gregorianDay;

  let jalaliDayNumber = dayNumber - 79;
  const jalaliCycles = div(jalaliDayNumber, 12053);
  jalaliDayNumber %= 12053;

  let jalaliYear = 979 + 33 * jalaliCycles + 4 * div(jalaliDayNumber, 1461);
  jalaliDayNumber %= 1461;

  if (jalaliDayNumber >= 366) {
    jalaliYear += div(jalaliDayNumber - 1, 365);
    jalaliDayNumber = (jalaliDayNumber - 1) % 365;
  }

  let jalaliMonth = 0;
  while (jalaliMonth < 11 && jalaliDayNumber >= JALALI_MONTH_DAYS[jalaliMonth]) {
    jalaliDayNumber -= JALALI_MONTH_DAYS[jalaliMonth];
    jalaliMonth += 1;
  }

  return { year: jalaliYear, month: jalaliMonth + 1, day: jalaliDayNumber + 1 };
}

export function toGregorian(jy: number, jm: number, jd: number): { year: number; month: number; day: number } {
  let jalaliYear = jy - 979;
  const jalaliMonth = jm - 1;
  const jalaliDay = jd - 1;

  let dayNumber = 365 * jalaliYear + div(jalaliYear, 33) * 8 + div((jalaliYear % 33) + 3, 4);
  for (let i = 0; i < jalaliMonth; i += 1) dayNumber += JALALI_MONTH_DAYS[i];
  dayNumber += jalaliDay;

  let gregorianDayNumber = dayNumber + 79;
  let gregorianYear = 1600 + 400 * div(gregorianDayNumber, 146097);
  gregorianDayNumber %= 146097;

  let leap = true;
  if (gregorianDayNumber >= 36525) {
    gregorianDayNumber -= 1;
    gregorianYear += 100 * div(gregorianDayNumber, 36524);
    gregorianDayNumber %= 36524;
    if (gregorianDayNumber >= 365) gregorianDayNumber += 1;
    else leap = false;
  }

  gregorianYear += 4 * div(gregorianDayNumber, 1461);
  gregorianDayNumber %= 1461;

  if (gregorianDayNumber >= 366) {
    leap = false;
    gregorianDayNumber -= 1;
    gregorianYear += div(gregorianDayNumber, 365);
    gregorianDayNumber %= 365;
  }

  let gregorianMonth = 0;
  while (gregorianDayNumber >= GREGORIAN_MONTH_DAYS[gregorianMonth] + (gregorianMonth === 1 && leap ? 1 : 0)) {
    gregorianDayNumber -= GREGORIAN_MONTH_DAYS[gregorianMonth] + (gregorianMonth === 1 && leap ? 1 : 0);
    gregorianMonth += 1;
  }

  return { year: gregorianYear, month: gregorianMonth + 1, day: gregorianDayNumber + 1 };
}

export function isJalaliLeapYear(year: number): boolean {
  const gregorian = toGregorian(year, 12, 30);
  const jalali = toJalali(gregorian.year, gregorian.month, gregorian.day);
  return jalali.year === year && jalali.month === 12 && jalali.day === 30;
}

export function daysInJalaliMonth(year: number, month: number): number {
  if (month < 1 || month > 12) return 31;
  if (month < 12) return JALALI_MONTH_DAYS[month - 1];
  return isJalaliLeapYear(year) ? 30 : 29;
}

export function isoToJalali(value: string): JalaliDateParts | null {
  const parsed = parseIsoDate(value);
  if (!parsed) return null;
  return toJalali(parsed.year, parsed.month, parsed.day);
}

export function jalaliToIso({ year, month, day }: JalaliDateParts): string {
  const gregorian = toGregorian(year, month, day);
  return `${gregorian.year}-${pad(gregorian.month)}-${pad(gregorian.day)}`;
}

export function todayJalali(): JalaliDateParts {
  const now = new Date();
  return toJalali(now.getFullYear(), now.getMonth() + 1, now.getDate());
}

export function formatJalaliDate(parts: JalaliDateParts): string {
  return `${parts.year}/${pad(parts.month)}/${pad(parts.day)}`.replace(/\d/g, (digit) => Number(digit).toLocaleString("fa-IR"));
}

export function quickReportRange(key: ReportFilterKey): { from_date: string; to_date: string } | { from_date: ""; to_date: "" } {
  if (key === "all") return { from_date: "", to_date: "" };
  const now = new Date();
  const today = todayJalali();
  let fromDate: string;

  if (key === "week") {
    const start = new Date(now);
    const daysFromSaturday = (start.getDay() + 1) % 7;
    start.setDate(start.getDate() - daysFromSaturday);
    fromDate = isoDate(start);
  } else if (key === "month") {
    fromDate = jalaliToIso({ year: today.year, month: today.month, day: 1 });
  } else {
    fromDate = jalaliToIso({ year: today.year, month: 1, day: 1 });
  }

  return { from_date: fromDate, to_date: isoDate(now) };
}
