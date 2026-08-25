// VYOM WhatsApp connector — minimal real whatsapp-web.js wrapper.
//
// Launched as a child process by app/messaging/whatsapp_connector.py.
// Emits newline-delimited JSON events on stdout so the Python side
// never has to guess REST endpoints or scrape console output:
//   {"event":"qr","data":"<base64 PNG data URL>"}
//   {"event":"ready","data":{"pushname":"...","wid":"..."}}
//   {"event":"authenticated"}
//   {"event":"disconnected","reason":"..."}
//   {"event":"message","data":{"from":"...","body":"...","timestamp":...}}
// Accepts newline-delimited JSON commands on stdin:
//   {"cmd":"send","to":"91XXXXXXXXXX@c.us","body":"text"}
//   {"cmd":"status"}
'use strict';

const { Client, LocalAuth } = require('whatsapp-web.js');
const QRCode = require('qrcode');
const readline = require('readline');

const authPath = process.env.VYOM_WA_AUTH_PATH || '.wwebjs_auth';

const client = new Client({
  authStrategy: new LocalAuth({ dataPath: authPath }),
  puppeteer: { headless: true, args: ['--no-sandbox', '--disable-setuid-sandbox'] },
});

function emit(event, data) {
  process.stdout.write(JSON.stringify({ event, data: data ?? null }) + '\n');
}

client.on('qr', async (qr) => {
  try {
    const dataUrl = await QRCode.toDataURL(qr, { width: 320, margin: 1 });
    emit('qr', dataUrl);
  } catch (error) {
    emit('error', String(error));
  }
});

client.on('authenticated', () => emit('authenticated'));

client.on('ready', () => {
  const info = client.info || {};
  emit('ready', { pushname: info.pushname || null, wid: info.wid ? info.wid._serialized : null });
});

client.on('disconnected', (reason) => emit('disconnected', reason));

client.on('message', (message) => {
  emit('message', { from: message.from, body: message.body, timestamp: message.timestamp, isGroup: message.from.endsWith('@g.us') });
});

client.on('auth_failure', (message) => emit('auth_failure', message));

const rl = readline.createInterface({ input: process.stdin });
rl.on('line', async (line) => {
  let command;
  try {
    command = JSON.parse(line);
  } catch {
    return;
  }
  if (command.cmd === 'send') {
    try {
      await client.sendMessage(command.to, command.body);
      emit('send_result', { to: command.to, success: true });
    } catch (error) {
      emit('send_result', { to: command.to, success: false, error: String(error) });
    }
  } else if (command.cmd === 'status') {
    emit('status', { state: client.info ? 'ready' : 'connecting' });
  }
});

emit('starting');
client.initialize().catch((error) => emit('error', String(error)));

process.on('SIGTERM', async () => {
  try { await client.destroy(); } catch { /* best-effort */ }
  process.exit(0);
});
