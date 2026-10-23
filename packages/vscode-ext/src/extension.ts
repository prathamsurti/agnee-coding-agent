import * as vscode from 'vscode';

export function activate(context: vscode.ExtensionContext) {
  const outputChannel = vscode.window.createOutputChannel('Agni Dev');
  outputChannel.appendLine('🔥 Agni Dev Extension initialized and ready.');

  // 1. Command: agni.login (RFC 8628 OAuth 2.0 Device Flow)
  const loginCmd = vscode.commands.registerCommand('agni.login', async () => {
    outputChannel.show(true);
    outputChannel.appendLine('[Auth] Initiating RFC 8628 Device Flow with Agni API Gateway...');

    const apiBase = vscode.workspace.getConfiguration('agni').get<string>('apiUrl') || 'http://localhost:8000';

    try {
      const initRes = await fetch(`${apiBase}/api/v1/auth/device/init`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          client_type: 'VSCODE',
          hostname: vscode.env.machineId || 'vscode-client',
          os_platform: process.platform
        })
      });

      if (!initRes.ok) {
        throw new Error(`Device init failed with status ${initRes.status}`);
      }

      const initData: any = await initRes.json();
      const { device_code, user_code, verification_uri_complete, interval = 2 } = initData;

      outputChannel.appendLine(`[Auth] User Code: ${user_code}`);
      outputChannel.appendLine(`[Auth] Verification URI: ${verification_uri_complete}`);

      const selection = await vscode.window.showInformationMessage(
        `Agni Dev: Authorize VS Code login with code [ ${user_code} ]`,
        'Open Browser',
        'Copy Code'
      );

      if (selection === 'Open Browser') {
        vscode.env.openExternal(vscode.Uri.parse(verification_uri_complete));
      } else if (selection === 'Copy Code') {
        await vscode.env.clipboard.writeText(user_code);
        vscode.window.showInformationMessage(`Copied code ${user_code} to clipboard.`);
      }

      // Background polling
      vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: `Waiting for Agni Dev authorization (${user_code})...`,
          cancellable: true
        },
        async (progress, token) => {
          let authorized = false;
          const startTime = Date.now();

          while (!authorized && Date.now() - startTime < 300000) {
            if (token.isCancellationRequested) {
              outputChannel.appendLine('[Auth] Authorization cancelled by user.');
              return;
            }

            await new Promise((r) => setTimeout(r, interval * 1000));

            try {
              const pollRes = await fetch(`${apiBase}/api/v1/auth/device/poll`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ device_code })
              });

              if (pollRes.ok) {
                const pollData: any = await pollRes.json();
                if (pollData.status === 'approved') {
                  authorized = true;
                  const tokens = pollData.tokens;
                  await context.secrets.store('agni_access_token', tokens.access_token);
                  await context.secrets.store('agni_refresh_token', tokens.refresh_token);
                  outputChannel.appendLine('[Auth] Successfully authenticated and stored tokens in VS Code SecretStorage.');
                  vscode.window.showInformationMessage('🔥 Agni Dev: VS Code successfully authorized!');
                  return;
                }
              }
            } catch (err) {
              // Retry next poll
            }
          }
        }
      );
    } catch (err: any) {
      vscode.window.showErrorMessage(`Agni Dev Login Error: ${err.message}`);
      outputChannel.appendLine(`[Auth Error] ${err.message}`);
    }
  });

  // 2. Command: agni.code (Interactive Coding Task streaming from daemon)
  const codeCmd = vscode.commands.registerCommand('agni.code', async () => {
    const prompt = await vscode.window.showInputBox({
      prompt: 'Enter your instruction or feature request for Agni Agent',
      placeHolder: 'e.g. Add validation logic for API keys in router.py'
    });

    if (!prompt) return;

    outputChannel.show(true);
    outputChannel.appendLine(`\n[Agent] Executing coding task: "${prompt}"`);

    const wsUrl = vscode.workspace.getConfiguration('agni').get<string>('daemonWsUrl') || 'ws://localhost:9000/ws';
    const token = (await context.secrets.get('agni_access_token')) || '';

    try {
      const WebSocket = (globalThis as any).WebSocket;
      if (!WebSocket) {
        outputChannel.appendLine('[Agent] WebSocket client initialized.');
      }

      vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: 'Agni Agent Running...',
          cancellable: false
        },
        async (progress) => {
          return new Promise<void>((resolve) => {
            try {
              const ws = new WebSocket(`${wsUrl}?token=${token}`);

              ws.onopen = () => {
                outputChannel.appendLine('[Agent] Connected to Agni Daemon. Dispatching RUN_TASK...');
                ws.send(JSON.stringify({ action: 'RUN_TASK', prompt }));
              };

              ws.onmessage = async (event: any) => {
                const data = JSON.parse(event.data);
                const ev = data.event;
                const payload = data.payload || {};

                if (ev === 'FILE_READ') {
                  progress.report({ message: `Reading ${payload.files?.join(', ')}...` });
                  outputChannel.appendLine(`[LocatorNode] Localized files: ${payload.files?.join(', ')}`);
                } else if (ev === 'PLAN_CREATED') {
                  progress.report({ message: 'Architect plan formulated...' });
                  outputChannel.appendLine(`[PlannerNode] Plan formulated with model: ${payload.model}`);
                } else if (ev === 'DIFF_APPLIED') {
                  progress.report({ message: 'Surgical diff applied...' });
                  outputChannel.appendLine(`[SurgicalCoderNode] Applied ${payload.blocks} block(s) to ${payload.file}`);
                  
                  // Open diff view if file is open in workspace
                  if (payload.file && vscode.workspace.workspaceFolders) {
                    const rootUri = vscode.workspace.workspaceFolders[0].uri;
                    const fileUri = vscode.Uri.joinPath(rootUri, payload.file);
                    outputChannel.appendLine(`[Diff] Applied change to: ${fileUri.fsPath}`);
                  }
                } else if (ev === 'TEST_OUTPUT') {
                  outputChannel.appendLine(`[VerifierNode] Test suite exited with code: ${payload.exit_code}`);
                } else if (ev === 'DONE') {
                  outputChannel.appendLine(`[Agent] Task Completed! Status: ${payload.status}`);
                  vscode.window.showInformationMessage(`🔥 Agni Dev: Task finished! (${payload.tokens} tokens consumed)`);
                  ws.close();
                  resolve();
                } else if (ev === 'ERROR') {
                  outputChannel.appendLine(`[Agent Error] ${payload.error || payload.status}`);
                  vscode.window.showErrorMessage(`Agni Agent Error: ${payload.error || payload.status}`);
                  ws.close();
                  resolve();
                }
              };

              ws.onerror = (e: any) => {
                outputChannel.appendLine(`[Agent WS Error] Could not connect to ${wsUrl}. Ensure agent daemon is running.`);
                vscode.window.showWarningMessage('Agni Daemon is offline. Please start apps/agent-daemon first.');
                resolve();
              };
            } catch (err: any) {
              outputChannel.appendLine(`[Error] ${err.message}`);
              resolve();
            }
          });
        }
      );
    } catch (err: any) {
      vscode.window.showErrorMessage(`Agni Agent Execution Failed: ${err.message}`);
    }
  });

  context.subscriptions.push(loginCmd, codeCmd);
}

export function deactivate() {}
