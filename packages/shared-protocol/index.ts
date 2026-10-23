/**
 * Agni Dev - Shared Protocol TypeScript Schemas
 * Synchronized with packages/shared-protocol/shared_protocol/schemas.py
 */

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type?: string;
  expires_in: number;
  user_id: string;
  workspace_id: string;
  plan_tier?: string;
}

export interface DeviceInitResponse {
  device_code: string;
  user_code: string;
  verification_uri: string;
  verification_uri_complete: string;
  expires_in: number;
  interval: number;
}

export interface DeviceLookupResponse {
  user_code: string;
  client_type: string;
  hostname?: string;
  os_platform?: string;
  ip?: string;
  status: string;
}

export interface DevicePollResponse {
  status: 'authorization_pending' | 'approved' | 'expired' | 'denied';
  tokens?: TokenResponse;
}

export interface AgentRunTelemetry {
  run_id: string;
  workspace_id?: string;
  user_id?: string;
  repo_name?: string;
  task_prompt?: string;
  status: string;
  iterations: number;
  input_tokens: number;
  output_tokens: number;
  duration_ms: number;
  final_diff?: string;
}

export type WsRpcEventType =
  | 'CONNECTED'
  | 'PLAN_CREATED'
  | 'FILE_READ'
  | 'DIFF_APPLIED'
  | 'TEST_OUTPUT'
  | 'HUMAN_APPROVAL_REQUIRED'
  | 'ERROR'
  | 'DONE'
  | 'PONG';

export interface WsRpcMessage {
  event: WsRpcEventType;
  run_id?: string;
  payload: Record<string, any>;
  timestamp?: string;
}
