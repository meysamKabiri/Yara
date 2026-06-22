import { useRef } from "react";
import type { PendingInterpretation, Worker } from "../api";
import { ROLE_OPTIONS } from "../constants";
import type { SetupEntity } from "../types/domain";
import { SetupModal } from "./setup/SetupModal";
import { FinancialModal } from "./financial/FinancialModal";
import { EntityUpdateModal } from "./entity/EntityUpdateModal";
import { SplitFlowModal } from "./split/SplitFlowModal";

type UnknownEntityForm = { workerId: string; name: string; type: string; roleDetail: string };
type EntityOverride = { name: string; type: string; roleDetail?: string | null };
type ConfirmPayload = {
  entity_id?: number | null;
  selected_person_id?: number | null;
  confirmed?: boolean;
  create_new?: boolean;
  name?: string | null;
  role?: string | null;
  role_detail?: string | null;
};

type FlowType = "ROLE_FLOW" | "PROFILE_FLOW" | "FINANCIAL_FLOW";

interface DomainUIControllerProps {
  interpretations: PendingInterpretation[];
  workers: Worker[];
  activeProjectId: number | null;
  isLoading: boolean;

  setupEditEntities: Record<number, SetupEntity[]>;
  candidateSelections: Record<number, string>;
  unknownEntityForms: Record<number, UnknownEntityForm>;

  setSetupEditEntities: (entities: Record<number, SetupEntity[]>) => void;
  setCandidateSelections: (selections: Record<number, string>) => void;
  setUnknownEntityForms: (forms: Record<number, UnknownEntityForm>) => void;

  onConfirm: (interpretation: PendingInterpretation, payload?: ConfirmPayload) => Promise<void>;
  onConfirmFinancial: (interpretation: PendingInterpretation, payload?: ConfirmPayload) => Promise<void>;
  onConfirmRole: (interpretation: PendingInterpretation, payload?: ConfirmPayload, entityOverride?: EntityOverride) => Promise<void>;
  onConfirmCandidate: (interpretation: PendingInterpretation, payload: ConfirmPayload, entityOverride?: EntityOverride) => Promise<void>;
  onDiscard: (interpretation: PendingInterpretation) => Promise<void>;
  onResolveUnknownEntity: (interpretation: PendingInterpretation) => Promise<void>;

  onConfirmSetupEntities: (interpretation: PendingInterpretation, entities: SetupEntity[]) => Promise<void>;
  onConfirmFinancialTransaction: (
    interpretation: PendingInterpretation,
    data: { entity_id: number; amount: string; direction: string; payment_method: string },
  ) => Promise<void>;
  onConfirmMixed: (
    interpretation: PendingInterpretation,
    setupEntities: SetupEntity[],
    financialData: { entity_id: number; amount: string; direction: string; payment_method: string },
  ) => Promise<void>;
  onConfirmEntityUpdate: (
    interpretation: PendingInterpretation,
    data: { name: string; phone: string | null; accountNumber: string | null; role: string; roleDetail: string | null },
  ) => Promise<void>;
}

function firstEntity(interpretation: PendingInterpretation): Record<string, unknown> {
  return interpretation.extracted_entities?.[0] ?? {};
}

function entityName(interpretation: PendingInterpretation): string {
  const entity = firstEntity(interpretation);
  return typeof entity.name === "string" && entity.name.trim() ? entity.name.trim() : "نامشخص";
}

function isUnknownEntity(interpretation: PendingInterpretation): boolean {
  const name = entityName(interpretation);
  return name === "نامشخص" || name === "طرف حساب نامشخص" || name === "ناشناس" || name.toLowerCase() === "unknown";
}

function hasExplicitCreateNew(interpretation: PendingInterpretation): boolean {
  return firstEntity(interpretation).create_new === true;
}

function candidateMatches(interpretation: PendingInterpretation, workers: Worker[]): Worker[] {
  const rawCandidates = firstEntity(interpretation).candidate_matches;
  if (!Array.isArray(rawCandidates)) return [];
  const ids = rawCandidates
    .map((candidate) =>
      typeof candidate === "object" && candidate !== null && "person_id" in candidate
        ? Number((candidate as Record<string, unknown>).person_id)
        : null,
    )
    .filter((id): id is number => Number.isFinite(id));
  return ids.map((id) => workers.find((worker) => worker.id === id)).filter((worker): worker is Worker => Boolean(worker));
}

function allowsVendorAutoCreate(_interpretation: PendingInterpretation): boolean {
  return false;
}

function isEntityProfileUpdate(interpretation: PendingInterpretation): boolean {
  const si = interpretation.structured_interpretation as Record<string, unknown> | null;
  return interpretation.semantic_action === "ENTITY_UPDATE" || si?.action === "UPDATE_ENTITY";
}

function isRoleAssignment(interpretation: PendingInterpretation): boolean {
  const si = interpretation.structured_interpretation as Record<string, unknown> | null;
  return interpretation.semantic_action === "SET_ROLE" || si?.intent === "SET_ROLE" || si?.action === "SET_ROLE";
}

function needsFinancialEntityResolution(interpretation: PendingInterpretation): boolean {
  return interpretation.canonical_event_type === "FINANCIAL_EVENT" && !interpretation.suggested_entity_id && !hasExplicitCreateNew(interpretation) && !allowsVendorAutoCreate(interpretation);
}

function needsProfileEntityResolution(interpretation: PendingInterpretation): boolean {
  return interpretation.canonical_event_type === "SETUP_EVENT" && isEntityProfileUpdate(interpretation) && !hasExplicitCreateNew(interpretation);
}

function entityTypeFromRecord(entity: Record<string, unknown>): string {
  const projectRole = typeof entity.project_role === "string" ? entity.project_role : undefined;
  const type = typeof entity.type === "string" ? entity.type : undefined;
  const roleGuess = typeof entity.role_guess === "string" ? entity.role_guess : undefined;
  const candidate = projectRole ?? type ?? roleGuess;
  if (candidate === "CLIENT") return "CLIENT";
  if (candidate === "VENDOR") return "VENDOR";
  if (candidate === "SKILLED" || candidate === "SKILLED_WORKER") return "SKILLED_WORKER";
  if (candidate === "DAILY_WORKER" || candidate === "WORKER") return "DAILY_WORKER";
  return "OTHER";
}

function preferredEntityType(interpretation: PendingInterpretation): string {
  return entityTypeFromRecord(firstEntity(interpretation));
}

function setupEntities(interpretation: PendingInterpretation): SetupEntity[] {
  return (interpretation.extracted_entities ?? [])
    .map((entity) => {
      const updates = typeof entity.field_updates === "object" && entity.field_updates !== null
        ? entity.field_updates as Record<string, unknown>
        : {};
      return {
        name: typeof entity.name === "string" ? entity.name : "",
        type: entityTypeFromRecord(entity),
        roleDetail: textValue(updates.role_detail ?? entity.role_detail),
        phone: textValue(updates.phone ?? entity.phone),
        accountNumber: textValue(updates.account_number ?? entity.account_number),
        dailyRate: textValue(updates.daily_rate ?? entity.daily_rate),
        notes: textValue(updates.notes ?? entity.notes),
        roleUpdate: textValue(updates.project_role ?? updates.type),
      };
    })
    .filter((entity) => entity.name.trim());
}

function textValue(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number") return String(value);
  return null;
}

function newEntityForm(interpretation: PendingInterpretation): UnknownEntityForm {
  const entity = setupEntities(interpretation)[0];
  return {
    workerId: "",
    name: entityName(interpretation) === "نامشخص" ? "" : entityName(interpretation),
    type: entity?.type ?? preferredEntityType(interpretation),
    roleDetail: entity?.roleDetail ?? "",
  };
}

function shouldShowRoleDetail(type: string): boolean {
  return type === "SKILLED_WORKER" || type === "OTHER";
}

function roleLabelFromType(type: string | undefined): string {
  if (type === "CLIENT") return "کارفرما";
  if (type === "VENDOR") return "فروشنده";
  if (type === "SKILLED_WORKER") return "استادکار";
  if (type === "DAILY_WORKER") return "کارگر";
  if (type === "OTHER") return "سایر";
  return "فرد";
}

function workerDisplayRole(worker: Worker): string {
  if ((worker.type === "SKILLED_WORKER" || worker.type === "OTHER") && worker.role_detail?.trim()) {
    return worker.role_detail.trim();
  }
  return roleLabelFromType(worker.type);
}

function workerOptionLabel(worker: Worker): string {
  return `${worker.name} - ${workerDisplayRole(worker)}`;
}

function flowType(interpretation: PendingInterpretation): FlowType {
  if (interpretation.domain_route?.domain === "FINANCIAL") return "FINANCIAL_FLOW";
  if (interpretation.domain_route?.domain === "SETUP") {
    if (isRoleAssignment(interpretation)) return "ROLE_FLOW";
    return "PROFILE_FLOW";
  }
  if (isRoleAssignment(interpretation)) return "ROLE_FLOW";
  if (isEntityProfileUpdate(interpretation)) return "PROFILE_FLOW";
  if (interpretation.canonical_event_type === "FINANCIAL_EVENT") return "FINANCIAL_FLOW";
  return "PROFILE_FLOW";
}

function unresolvedEntityTitle(interpretation: PendingInterpretation): string {
  const name = entityName(interpretation);
  if (needsProfileEntityResolution(interpretation)) return `${name} در پروژه پیدا نشد.`;
  const role = roleLabelFromType(preferredEntityType(interpretation));
  if (name === "نامشخص" || name === "طرف حساب نامشخص") return "طرف حساب در پروژه پیدا نشد.";
  return `${role} «${name}» در پروژه پیدا نشد.`;
}

function unresolvedEntityHelp(interpretation: PendingInterpretation): string {
  if (needsProfileEntityResolution(interpretation)) return "فرد مورد نظر را انتخاب کنید یا فرد جدید بسازید.";
  const role = roleLabelFromType(preferredEntityType(interpretation));
  return `یک ${role} موجود را انتخاب کنید یا ${role} جدید ایجاد کنید.`;
}

export function DomainUIController({
  interpretations,
  workers,
  activeProjectId,
  isLoading,
  setupEditEntities,
  candidateSelections,
  unknownEntityForms,
  setSetupEditEntities,
  setCandidateSelections,
  setUnknownEntityForms,
  onConfirm,
  onConfirmFinancial,
  onConfirmRole,
  onConfirmCandidate,
  onDiscard,
  onResolveUnknownEntity,
  onConfirmSetupEntities,
  onConfirmFinancialTransaction,
  onConfirmMixed,
  onConfirmEntityUpdate,
}: DomainUIControllerProps) {

  if (interpretations.length === 0) return null;

  const splitSetupData = useRef<{
    name: string;
    type: string;
    roleDetail: string | null;
    phone: string | null;
    accountNumber: string | null;
  } | null>(null);

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="interpretation-title">
      <section className="confirmation-modal">
        <div className="modal-header">
          <div>
            <span className="eyebrow">تایید</span>
            <h2 id="interpretation-title">مورد پیشنهادی را قبل از ثبت بررسی کنید</h2>
            <p>هیچ چیزی بدون تایید شما در دفتر پروژه ثبت نمی‌شود.</p>
          </div>
        </div>

        <div className="interpretation-stack">
          {interpretations.map((interpretation) => {
            const domain = interpretation.domain_route?.domain;
            const ft = flowType(interpretation);
            const candidates = candidateMatches(interpretation, workers);

            // MIXED domain
            if (domain === "MIXED") {
              return (
                <SplitFlowModal
                  key={interpretation.id}
                  interpretation={interpretation}
                  workers={workers}
                  activeProjectId={activeProjectId}
                  isLoading={isLoading}
                  onConfirm={(data) => {
                    onConfirmMixed(interpretation, [
                      {
                        ...data.setup,
                        dailyRate: null,
                        notes: null,
                        roleUpdate: data.setup.type,
                      },
                    ], data.financial);
                  }}
                  onDiscard={() => onDiscard(interpretation)}
                />
              );
            }

            // Entity resolution pre-step for unknown entities
            if (candidates.length === 0 && (isUnknownEntity(interpretation) || needsFinancialEntityResolution(interpretation) || needsProfileEntityResolution(interpretation) || interpretation.canonical_event_type === "SETUP_EVENT")) {
              const form = unknownEntityForms[interpretation.id] ?? newEntityForm(interpretation);
              const canContinue = Boolean(form.name.trim() && form.type);
              return (
                <article className="interpretation-card" key={interpretation.id}>
                  <h3>{unresolvedEntityTitle(interpretation)}</h3>
                  <p className="muted">
                    {interpretation.canonical_event_type === "SETUP_EVENT"
                      ? "این فرد به عنوان شخص جدید در پروژه ثبت می‌شود."
                      : unresolvedEntityHelp(interpretation)}
                  </p>
                  <div className="edit-grid">
                    <label>
                      نام
                      <input
                        value={form.name}
                        onChange={(event) =>
                          setUnknownEntityForms({
                            ...unknownEntityForms,
                            [interpretation.id]: { ...form, name: event.target.value },
                          })
                        }
                      />
                    </label>
                    <label>
                      نقش
                      <select
                        value={form.type}
                        onChange={(event) =>
                          setUnknownEntityForms({
                            ...unknownEntityForms,
                            [interpretation.id]: { ...form, type: event.target.value },
                          })
                        }
                      >
                        {ROLE_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </label>
                    {shouldShowRoleDetail(form.type) && (
                      <label>
                        تخصص / توضیح نقش
                        <input
                          value={form.roleDetail}
                          onChange={(event) =>
                            setUnknownEntityForms({
                              ...unknownEntityForms,
                              [interpretation.id]: { ...form, roleDetail: event.target.value },
                            })
                          }
                        />
                      </label>
                    )}
                  </div>
                  <div className="modal-actions">
                    <button
                      className="primary-action"
                      type="button"
                      onClick={() => {
                        const entityOverride: EntityOverride = {
                          name: form.name.trim(),
                          type: form.type,
                          roleDetail: form.roleDetail.trim() || null,
                        };
                        const createPayload: ConfirmPayload = {
                          create_new: true,
                          name: entityOverride.name,
                          role: entityOverride.type,
                          role_detail: entityOverride.roleDetail,
                        };
                        if (ft === "ROLE_FLOW") {
                          onConfirmRole(interpretation, createPayload, entityOverride);
                        } else {
                          onConfirmCandidate(interpretation, createPayload, entityOverride);
                        }
                      }}
                      disabled={isLoading || !canContinue}
                    >
                      تأیید
                    </button>
                    <button
                      className="danger-action"
                      type="button"
                      onClick={() => onDiscard(interpretation)}
                      disabled={isLoading}
                    >
                      حذف
                    </button>
                  </div>
                </article>
              );
            }

            // Candidates exist
            if (candidates.length > 0) {
              const selectionValue = candidateSelections[interpretation.id] ?? String(candidates[0].id);
              const isCreatingNewCandidate = selectionValue === "create-new";
              const selectedCandidate = isCreatingNewCandidate
                ? undefined
                : candidates.find((worker) => String(worker.id) === selectionValue) ?? candidates[0];
              const roleEntities = setupEditEntities[interpretation.id] ?? setupEntities(interpretation);
              const editableRoleEntities = roleEntities.length ? roleEntities : setupEntities(interpretation);
              const createForm = unknownEntityForms[interpretation.id] ?? newEntityForm(interpretation);
              const displayedName = isCreatingNewCandidate ? createForm.name : selectedCandidate?.name ?? "";
              const displayedRole = isCreatingNewCandidate
                ? createForm.type
                : selectedCandidate?.type ?? preferredEntityType(interpretation);
              const displayedRoleDetail = isCreatingNewCandidate
                ? createForm.roleDetail
                : selectedCandidate?.role_detail ?? "";
              const canConfirmCandidate = Boolean(
                isCreatingNewCandidate ? createForm.name.trim() && createForm.type : selectedCandidate,
              );
              return (
                <article className="interpretation-card" key={interpretation.id}>
                  <h3>
                    {ft === "ROLE_FLOW"
                      ? "تعیین نقش فرد"
                      : preferredEntityType(interpretation) === "VENDOR"
                        ? "کدام فروشنده مدنظر است؟"
                        : `«${entityName(interpretation)}» کدام فرد است؟`}
                  </h3>
                  {ft === "ROLE_FLOW" && <p className="muted">نقش این شخص در پروژه را مشخص کنید</p>}
                  <div className="edit-grid">
                    <label>
                      انتخاب فرد
                      <select
                        value={selectionValue}
                        onChange={(event) =>
                          setCandidateSelections({
                            ...candidateSelections,
                            [interpretation.id]: event.target.value,
                          })
                        }
                      >
                        {candidates.map((worker) => (
                          <option key={worker.id} value={worker.id}>
                            {workerOptionLabel(worker)}
                          </option>
                        ))}
                        <option value="create-new">
                          ایجاد فرد جدید با نام «{entityName(interpretation)}»
                        </option>
                      </select>
                    </label>
                    <label>
                      نام
                      <input
                        value={displayedName}
                        readOnly={!isCreatingNewCandidate}
                        onChange={(event) =>
                          setUnknownEntityForms({
                            ...unknownEntityForms,
                            [interpretation.id]: { ...createForm, name: event.target.value },
                          })
                        }
                      />
                    </label>
                    {isCreatingNewCandidate || ft === "ROLE_FLOW" ? (
                      <>
                        <label>
                          نقش
                          <select
                            value={ft === "ROLE_FLOW" && !isCreatingNewCandidate ? (editableRoleEntities[0]?.type ?? displayedRole) : displayedRole}
                            disabled={!isCreatingNewCandidate && ft !== "ROLE_FLOW"}
                            onChange={(event) => {
                              if (ft === "ROLE_FLOW" && !isCreatingNewCandidate) {
                                setSetupEditEntities({
                                  ...setupEditEntities,
                                  [interpretation.id]: editableRoleEntities.map((item, itemIndex) =>
                                    itemIndex === 0 ? { ...item, type: event.target.value } : item,
                                  ),
                                });
                              } else {
                                setUnknownEntityForms({
                                  ...unknownEntityForms,
                                  [interpretation.id]: { ...createForm, type: event.target.value },
                                });
                              }
                            }}
                          >
                            {ROLE_OPTIONS.map((option) => (
                              <option key={option.value} value={option.value}>
                                {option.label}
                              </option>
                            ))}
                          </select>
                        </label>
                        {shouldShowRoleDetail(displayedRole) && (
                          <label>
                            تخصص / توضیح نقش
                            <input
                              value={displayedRoleDetail}
                              readOnly={!isCreatingNewCandidate}
                              onChange={(event) =>
                                setUnknownEntityForms({
                                  ...unknownEntityForms,
                                  [interpretation.id]: { ...createForm, roleDetail: event.target.value },
                                })
                              }
                            />
                          </label>
                        )}
                      </>
                    ) : (
                      <label>
                        نقش فعلی
                        <input
                          value={selectedCandidate ? workerDisplayRole(selectedCandidate) : roleLabelFromType(displayedRole)}
                          readOnly
                        />
                      </label>
                    )}
                  </div>
                  <div className="modal-actions">
                    <button
                      className="primary-action"
                      type="button"
                      onClick={() => {
                        if (isCreatingNewCandidate) {
                          const entityOverride: EntityOverride = {
                            name: createForm.name.trim(),
                            type: createForm.type,
                            roleDetail: createForm.roleDetail.trim() || null,
                          };
                          const createPayload: ConfirmPayload = {
                            create_new: true,
                            name: entityOverride.name,
                            role: entityOverride.type,
                            role_detail: entityOverride.roleDetail,
                          };
                          if (ft === "ROLE_FLOW") {
                            onConfirmRole(interpretation, createPayload, entityOverride);
                          } else {
                            onConfirmCandidate(interpretation, createPayload, entityOverride);
                          }
                          return;
                        }
                        if (selectedCandidate) {
                          if (ft === "ROLE_FLOW") {
                            onConfirmRole(interpretation, { selected_person_id: selectedCandidate.id });
                          } else {
                            onConfirm(
                              interpretation,
                              interpretation.canonical_event_type === "FINANCIAL_EVENT"
                                ? { entity_id: selectedCandidate.id, confirmed: true }
                                : { selected_person_id: selectedCandidate.id },
                            );
                          }
                        }
                      }}
                      disabled={isLoading || !canConfirmCandidate}
                    >
                      تأیید
                    </button>
                    {ft !== "ROLE_FLOW" && (
                      <button
                        className="danger-action"
                        type="button"
                        onClick={() => onDiscard(interpretation)}
                        disabled={isLoading}
                      >
                        حذف
                      </button>
                    )}
                  </div>
                </article>
              );
            }

            // Role flow (entity known, no candidates)
            if (ft === "ROLE_FLOW") {
              const roleEntities = setupEditEntities[interpretation.id] ?? setupEntities(interpretation);
              const editableEntities = roleEntities.length ? roleEntities : setupEntities(interpretation);
              return (
                <article className="interpretation-card" key={interpretation.id}>
                  <section className="approval-section">
                    <h3>تعیین نقش فرد</h3>
                    <p className="muted">نقش این شخص در پروژه را مشخص کنید</p>
                    <div className="edit-grid">
                      {editableEntities.slice(0, 1).map((entity, index) => (
                        <div className="setup-edit-row" key={`role-${interpretation.id}-${index}`}>
                          <label>
                            نام
                            <input
                              value={entity.name}
                              onChange={(event) =>
                                setSetupEditEntities({
                                  ...setupEditEntities,
                                  [interpretation.id]: editableEntities.map((item, itemIndex) =>
                                    itemIndex === index ? { ...item, name: event.target.value } : item,
                                  ),
                                })
                              }
                            />
                          </label>
                          <label>
                            نقش
                            <select
                              value={entity.type}
                              onChange={(event) =>
                                setSetupEditEntities({
                                  ...setupEditEntities,
                                  [interpretation.id]: editableEntities.map((item, itemIndex) =>
                                    itemIndex === index ? { ...item, type: event.target.value } : item,
                                  ),
                                })
                              }
                            >
                              {ROLE_OPTIONS.map((option) => (
                                <option key={option.value} value={option.value}>
                                  {option.label}
                                </option>
                              ))}
                            </select>
                          </label>
                          {shouldShowRoleDetail(entity.type) && (
                            <label>
                              تخصص / توضیح نقش
                              <input
                                value={entity.roleDetail ?? ""}
                                onChange={(event) =>
                                  setSetupEditEntities({
                                    ...setupEditEntities,
                                    [interpretation.id]: editableEntities.map((item, itemIndex) =>
                                      itemIndex === index ? { ...item, roleDetail: event.target.value } : item,
                                    ),
                                  })
                                }
                              />
                            </label>
                          )}
                        </div>
                      ))}
                    </div>
                  </section>
                  <div className="modal-actions">
                    <button
                      className="primary-action"
                      type="button"
                      onClick={() => {
                        const entity = editableEntities[0];
                        onConfirmRole(interpretation, {
                          create_new: true,
                          name: entity.name.trim(),
                          role: entity.type,
                          role_detail: entity.roleDetail || null,
                        });
                      }}
                      disabled={isLoading || editableEntities.length === 0 || !editableEntities[0].name.trim()}
                    >
                      تأیید
                    </button>
                  </div>
                </article>
              );
            }

            // Domain routing - clean switch with NO OTHER LOGIC
            switch (domain) {
              case "SETUP":
                return (
                  <SetupModal
                    key={interpretation.id}
                    interpretation={interpretation}
                    workers={workers}
                    activeProjectId={activeProjectId}
                    isLoading={isLoading}
                    onConfirm={(entities) => onConfirmSetupEntities(interpretation, entities)}
                    onDiscard={() => onDiscard(interpretation)}
                  />
                );
              case "FINANCIAL":
                return (
                  <FinancialModal
                    key={interpretation.id}
                    interpretation={interpretation}
                    workers={workers}
                    activeProjectId={activeProjectId}
                    isLoading={isLoading}
                    onConfirm={(data) => onConfirmFinancialTransaction(interpretation, data)}
                    onDiscard={() => onDiscard(interpretation)}
                  />
                );
              case "ENTITY_UPDATE":
                return (
                  <EntityUpdateModal
                    key={interpretation.id}
                    interpretation={interpretation}
                    workers={workers}
                    activeProjectId={activeProjectId}
                    isLoading={isLoading}
                    onConfirm={(data) => onConfirmEntityUpdate(interpretation, data)}
                    onDiscard={() => onDiscard(interpretation)}
                  />
                );
              default:
                return null;
            }
          })}
        </div>
      </section>
    </div>
  );
}
