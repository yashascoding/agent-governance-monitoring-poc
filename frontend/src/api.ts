import axios from "axios";

export const api = axios.create({ baseURL: "/api", timeout: 15000 });
api.interceptors.request.use((request) => {
  const token = sessionStorage.getItem("access_token");
  if (token) request.headers.Authorization = `Bearer ${token}`;
  return request;
});

export function messageFromError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    return typeof detail === "string" ? detail : error.message;
  }
  return error instanceof Error ? error.message : "Unexpected error";
}

export type User = { id: string; email: string; role: "APPROVER" | "VIEWER" };
export type Alert = {
  id: string;
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
  rule_id: string;
  rule_name: string;
  agent_id: string;
  execution_id: string;
  application_id?: string | null;
  description: string;
  evidence_event_ids: string[];
  evidence: Record<string, unknown>;
  status: "OPEN" | "ACKNOWLEDGED" | "RESOLVED";
  correlation_id: string;
  created_at: string;
};
export type EventRecord = {
  id: string;
  execution_id: string;
  event_type: string;
  action: string;
  timestamp: string;
  decision?: string | null;
  payload: Record<string, unknown>;
};
export type Application = {
  id: string;
  applicant_name: string;
  amount: string;
  purpose: string;
  status: string;
  execution_id: string;
  created_at: string;
  decision?: {
    decision: string;
    reason: string;
    signature_verified: boolean;
    decided_at: string;
  } | null;
};
