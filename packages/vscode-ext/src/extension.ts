/**
 * Agni Dev VS Code Extension Bridge
 * Connects directly to the local daemon (ws://localhost:9000/ws) via JSON-RPC.
 */
export function activate(context: any) {
  console.log("🔥 Agni Dev Extension activated.");

  // agni.login triggers RFC 8628 device flow
  // agni.code streams real-time DIFF_APPLIED and TEST_OUTPUT events
}

export function deactivate() {}
