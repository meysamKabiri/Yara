import type { PendingInterpretationConfirm } from "../api";

export interface NeedsSelectionCandidate {
  person_id?: number | string | null;
  worker_id?: number | string | null;
  name?: string;
  type?: string;
  score?: number | string;
  match_type?: string;
}

export function getCandidateEntityId(candidate: NeedsSelectionCandidate): number | null {
  const rawId = candidate.person_id ?? candidate.worker_id;
  const id = typeof rawId === "number" ? rawId : Number(rawId);
  return Number.isFinite(id) ? id : null;
}

export function buildConfirmPayload(entityId?: number | null): PendingInterpretationConfirm {
  return typeof entityId === "number" && Number.isFinite(entityId)
    ? { entity_id: entityId, confirmed: true }
    : { confirmed: true };
}

export function normalizeEntityName(value: string): string {
  return value
    .replace(/[\u064B-\u065F\u0670]/g, "")
    .replace(/\u200c/g, " ")
    .replace(/[يى]/g, "ی")
    .replace(/ك/g, "ک")
    .replace(/\s+/g, " ")
    .trim();
}

export function exactEntityIdByName<T extends { id: number; name: string }>(
  name: string,
  entities: T[],
): number | null {
  const normalizedName = normalizeEntityName(name);
  if (!normalizedName) return null;
  const matches = entities.filter((entity) => normalizeEntityName(entity.name) === normalizedName);
  return matches.length === 1 ? matches[0].id : null;
}

export function normalizeNeedsSelection(responseOrError: unknown): NeedsSelectionCandidate[] | null {
  let parsed = responseOrError;
  if (responseOrError instanceof Error) {
    try {
      parsed = JSON.parse(responseOrError.message);
    } catch {
      return null;
    }
  }

  const detail = typeof parsed === "object" && parsed !== null && "detail" in parsed
    ? (parsed as { detail?: unknown }).detail
    : parsed;
  if (
    typeof detail === "object"
    && detail !== null
    && (detail as { status?: unknown }).status === "NEEDS_SELECTION"
    && Array.isArray((detail as { candidates?: unknown }).candidates)
  ) {
    return (detail as { candidates: NeedsSelectionCandidate[] }).candidates;
  }
  return null;
}

export function exactNeedsSelectionEntityId(candidates: NeedsSelectionCandidate[] | null): number | null {
  if (!candidates) return null;
  const exactIds = candidates
    .filter((candidate) => candidate.match_type === "exact" && Number(candidate.score) === 1)
    .map(getCandidateEntityId)
    .filter((id): id is number => id !== null);
  const uniqueIds = [...new Set(exactIds)];
  return uniqueIds.length === 1 ? uniqueIds[0] : null;
}
