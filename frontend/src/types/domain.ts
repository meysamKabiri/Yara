export type DomainType =
  | "SETUP"
  | "FINANCIAL"
  | "ENTITY_UPDATE"
  | "MIXED";

export type SetupEntity = {
  name: string;
  type: string;
  roleDetail: string | null;
  phone: string | null;
  accountNumber: string | null;
  dailyRate?: string | null;
  notes?: string | null;
  roleUpdate?: string | null;
};
