import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

/** Typed client generated from the backend's OpenAPI schema (`npm run gen:api`). */
export const api = createClient<paths>({ baseUrl: "" });

export type CaseSummary = components["schemas"]["CaseSummary"];
export type CaseDetail = components["schemas"]["CaseDetail"];
export type Account = components["schemas"]["AccountOut"];
export type Health = components["schemas"]["Health"];

/** Unwrap an openapi-fetch result or throw, for use inside react-query. */
export function unwrap<T>(res: { data?: T; error?: unknown; response: Response }): T {
  if (res.error !== undefined || res.data === undefined) {
    throw new Error(`API ${res.response.status}: ${JSON.stringify(res.error)}`);
  }
  return res.data;
}
