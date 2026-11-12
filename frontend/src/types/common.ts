/** Shared primitives. Monetary amounts are in base currency unless a field states otherwise. */
export type ID = string;
export type IsoDateTime = string;
/** Business date as YYYY-MM-DD (BR-SAL-008). */
export type BusinessDate = string;
export type Currency = "USD" | "KHR";
export type ActiveStatus = "ACTIVE" | "INACTIVE";

export interface ListResponse<T> {
  items: T[];
  total: number;
  nextCursor: string | null;
}

export type ListParams = Record<string, string | number | boolean | undefined | null>;

export interface ApiFieldError {
  field?: string;
  code?: string;
  message: string;
  [key: string]: unknown;
}

/** Standard error envelope, SRS section 13.1. */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details: ApiFieldError[];
    correlation_id: string;
  };
}

export interface TimelineEvent {
  at: IsoDateTime;
  label: string;
  by: string;
  note?: string;
}
