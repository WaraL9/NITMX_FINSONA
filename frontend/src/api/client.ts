import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

/** Typed client generated from the backend's OpenAPI schema (`npm run gen:api`). */
export const api = createClient<paths>({ baseUrl: "" });

export type CaseSummary = components["schemas"]["CaseSummary"];
export type CaseDetail = components["schemas"]["CaseDetail"];
export type Account = components["schemas"]["AccountOut"];
export type Health = components["schemas"]["Health"];
export type DocumentOut = components["schemas"]["DocumentOut"];
export type Transaction = components["schemas"]["TransactionOut"];
export type TransactionPage = components["schemas"]["TransactionPage"];
export type ApiErrorBody = components["schemas"]["ApiError"];

/** Unwrap an openapi-fetch result or throw, for use inside react-query. */
export function unwrap<T>(res: { data?: T; error?: unknown; response: Response }): T {
  if (res.error !== undefined || res.data === undefined) {
    throw new Error(`API ${res.response.status}: ${JSON.stringify(res.error)}`);
  }
  return res.data;
}

export class UploadError extends Error {
  constructor(
    public status: number,
    public body: ApiErrorBody,
  ) {
    super(body.message);
  }
}

/** Multipart upload (kept outside openapi-fetch for simple FormData handling). */
export async function uploadDocument(
  caseId: number,
  file: File,
  opts: { password?: string; accountId?: number; kind?: DocumentOut["kind"] } = {},
): Promise<DocumentOut> {
  const form = new FormData();
  form.append("file", file);
  form.append("kind", opts.kind ?? "statement");
  if (opts.password) form.append("password", opts.password);
  if (opts.accountId !== undefined) form.append("account_id", String(opts.accountId));
  const res = await fetch(`/api/cases/${caseId}/documents`, { method: "POST", body: form });
  const body = await res.json().catch(() => ({ code: "network", message: res.statusText }));
  if (!res.ok) throw new UploadError(res.status, body as ApiErrorBody);
  return body as DocumentOut;
}

export const documentFileUrl = (documentId: number, page?: number | null) =>
  `/api/documents/${documentId}/file${page ? `#page=${page}` : ""}`;

export type Analysis = components["schemas"]["AnalysisOut"];
export type Sizing = components["schemas"]["SizingOut"];
export type WatchlistEntry = components["schemas"]["WatchlistOut"];
export type StatementReport = components["schemas"]["ParseReport"];
export type PP30Report = components["schemas"]["PP30ParseReport"];

export const isPP30Report = (r: StatementReport | PP30Report | null | undefined): r is PP30Report =>
  !!r && "period" in r && "amounts" in r;
