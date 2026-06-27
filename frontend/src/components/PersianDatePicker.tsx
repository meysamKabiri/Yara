import { useEffect, useId, useMemo, useRef, useState } from "react";
import { CalendarDays, ChevronLeft, ChevronRight, X } from "lucide-react";
import {
  daysInJalaliMonth,
  formatJalaliDate,
  isoToJalali,
  JalaliDateParts,
  jalaliToIso,
  todayJalali,
  toGregorian,
} from "../utils/jalaliDate";

type PersianDatePickerProps = {
  id?: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
};

const JALALI_MONTH_NAMES = [
  "فروردین",
  "اردیبهشت",
  "خرداد",
  "تیر",
  "مرداد",
  "شهریور",
  "مهر",
  "آبان",
  "آذر",
  "دی",
  "بهمن",
  "اسفند",
];

const WEEKDAY_LABELS = ["ش", "ی", "د", "س", "چ", "پ", "ج"];

function sameJalaliDay(a: JalaliDateParts | null, b: JalaliDateParts): boolean {
  return Boolean(a && a.year === b.year && a.month === b.month && a.day === b.day);
}

function normalizeMonth(year: number, month: number): JalaliDateParts {
  if (month < 1) return { year: year - 1, month: 12, day: 1 };
  if (month > 12) return { year: year + 1, month: 1, day: 1 };
  return { year, month, day: 1 };
}

function firstDayOffset(year: number, month: number): number {
  const gregorian = toGregorian(year, month, 1);
  const day = new Date(gregorian.year, gregorian.month - 1, gregorian.day).getDay();
  return (day + 1) % 7;
}

export function PersianDatePicker({ id, label, value, onChange }: PersianDatePickerProps) {
  const generatedId = useId();
  const controlId = id ?? generatedId;
  const rootRef = useRef<HTMLDivElement>(null);
  const selectedDate = useMemo(() => isoToJalali(value), [value]);
  const [isOpen, setIsOpen] = useState(false);
  const [activeMonth, setActiveMonth] = useState<JalaliDateParts>(() => {
    const initial = selectedDate ?? todayJalali();
    return { year: initial.year, month: initial.month, day: 1 };
  });

  useEffect(() => {
    if (!selectedDate) return;
    setActiveMonth({ year: selectedDate.year, month: selectedDate.month, day: 1 });
  }, [selectedDate?.year, selectedDate?.month]);

  useEffect(() => {
    if (!isOpen) return;
    function handlePointerDown(event: PointerEvent) {
      if (rootRef.current?.contains(event.target as Node)) return;
      setIsOpen(false);
    }
    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setIsOpen(false);
    }
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [isOpen]);

  const calendarDays = useMemo(() => {
    const offset = firstDayOffset(activeMonth.year, activeMonth.month);
    const days = daysInJalaliMonth(activeMonth.year, activeMonth.month);
    return [
      ...Array.from({ length: offset }, () => null),
      ...Array.from({ length: days }, (_, index) => ({
        year: activeMonth.year,
        month: activeMonth.month,
        day: index + 1,
      })),
    ];
  }, [activeMonth.month, activeMonth.year]);

  const displayValue = selectedDate ? formatJalaliDate(selectedDate) : "انتخاب تاریخ";

  function moveMonth(delta: number) {
    setActiveMonth((current) => normalizeMonth(current.year, current.month + delta));
  }

  function selectDate(parts: JalaliDateParts) {
    onChange(jalaliToIso(parts));
    setIsOpen(false);
  }

  function clearDate() {
    onChange("");
    setIsOpen(false);
  }

  return (
    <div className="date-field persian-date-field" ref={rootRef}>
      <label id={`${controlId}-label`}>{label}</label>
      <button
        aria-expanded={isOpen}
        aria-haspopup="dialog"
        aria-labelledby={`${controlId}-label ${controlId}-button-value`}
        className={value ? "persian-date-trigger has-value" : "persian-date-trigger"}
        id={`${controlId}-button`}
        type="button"
        onClick={() => setIsOpen((open) => !open)}
      >
        <CalendarDays aria-hidden="true" size={17} />
        <span id={`${controlId}-button-value`}>{displayValue}</span>
      </button>

      {isOpen && (
        <div aria-label={`انتخاب ${label}`} className="persian-date-popover" role="dialog">
          <div className="persian-calendar-head">
            <button aria-label="ماه قبل" type="button" onClick={() => moveMonth(-1)}><ChevronRight aria-hidden="true" size={17} /></button>
            <strong>{JALALI_MONTH_NAMES[activeMonth.month - 1]} {activeMonth.year.toLocaleString("fa-IR", { useGrouping: false })}</strong>
            <button aria-label="ماه بعد" type="button" onClick={() => moveMonth(1)}><ChevronLeft aria-hidden="true" size={17} /></button>
          </div>

          <div className="persian-calendar-weekdays" aria-hidden="true">
            {WEEKDAY_LABELS.map((weekday) => <span key={weekday}>{weekday}</span>)}
          </div>

          <div className="persian-calendar-grid">
            {calendarDays.map((day, index) => day ? (
              <button
                className={sameJalaliDay(selectedDate, day) ? "selected" : ""}
                key={`${day.year}-${day.month}-${day.day}`}
                type="button"
                onClick={() => selectDate(day)}
              >
                {day.day.toLocaleString("fa-IR")}
              </button>
            ) : <span aria-hidden="true" key={`empty-${index}`} />)}
          </div>

          <div className="persian-calendar-actions">
            <button type="button" onClick={() => selectDate(todayJalali())}>امروز</button>
            <button className="ghost-icon-action" type="button" onClick={clearDate}><X aria-hidden="true" size={15} />پاک کردن</button>
          </div>
        </div>
      )}
    </div>
  );
}
