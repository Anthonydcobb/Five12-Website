const { app, BrowserWindow, shell, ipcMain } = require('electron');
const { spawn }  = require('child_process');
const dgram      = require('dgram');
const path       = require('path');
const http       = require('http');

const PORT       = 5050;
const PYTHON     = 'C:\\Users\\antho\\AppData\\Local\\Programs\\Python\\Python312\\python.exe';
const ROOT       = path.join(__dirname, '..');
const BACKEND    = path.join(ROOT, 'backend');
const STATIC_DIR = path.join(ROOT, 'app', 'dist');

let flaskProcess = null;
let mainWindow   = null;

// ── Network monitor state ─────────────────────────────────────────────────────
let udpSocket         = null;
let universeMap       = new Map();  // universe# -> { lastSeen, sourceName, channels }
let subscribedUniverse = null;
let universeListTimer  = null;
let channelTimer       = null;

// ── sACN packet parser ────────────────────────────────────────────────────────
function parseSACN(buf) {
  if (buf.length < 126) return null;
  // ACN Packet Identifier at offset 4
  if (buf.slice(4, 12).toString('ascii') !== 'ASC-E1.17') return null;
  // Root PDU Vector = 0x00000004 (data packet)
  if (buf.readUInt32BE(18) !== 0x00000004) return null;
  // Framing PDU Vector = 0x00000002
  if (buf.readUInt32BE(40) !== 0x00000002) return null;

  const universe    = buf.readUInt16BE(113);
  const sourceName  = buf.slice(44, 108).toString('utf8').replace(/\0/g, '').trim();
  const propCount   = buf.readUInt16BE(123);
  const dmxLen      = Math.min(propCount > 0 ? propCount - 1 : 0, 512);
  const channels    = buf.slice(126, 126 + dmxLen);

  return { universe, sourceName, channels };
}

// ── Art-Net packet parser ─────────────────────────────────────────────────────
function parseArtNet(buf) {
  if (buf.length < 18) return null;
  if (buf.slice(0, 8).toString('ascii') !== 'Art-Net\0') return null;
  const opCode = buf.readUInt16LE(8);
  if (opCode !== 0x5000) return null;  // ArtDmx opcode

  const universe = buf.readUInt16LE(14) & 0x7FFF;
  const length   = buf.readUInt16BE(16);
  const channels = buf.slice(18, 18 + length);

  return { universe, sourceName: '', channels };
}

// ── sACN universe → multicast group ──────────────────────────────────────────
function sacnMulticast(universe) {
  return `239.255.${(universe >> 8) & 0xFF}.${universe & 0xFF}`;
}

// ── Network IPC handlers ──────────────────────────────────────────────────────
function setupNetworkIPC() {
  ipcMain.on('network:start', (_, protocol) => {
    // Tear down any existing socket
    if (udpSocket) { try { udpSocket.close(); } catch (_) {} udpSocket = null; }
    if (universeListTimer) { clearInterval(universeListTimer); universeListTimer = null; }
    if (channelTimer)      { clearInterval(channelTimer);      channelTimer = null; }
    universeMap.clear();
    subscribedUniverse = null;

    const port = protocol === 'sacn' ? 5568 : 6454;
    udpSocket = dgram.createSocket({ type: 'udp4', reuseAddr: true });

    udpSocket.on('message', (buf) => {
      const parsed = protocol === 'sacn' ? parseSACN(buf) : parseArtNet(buf);
      if (!parsed) return;

      const { universe, sourceName, channels } = parsed;
      const existing = universeMap.get(universe);

      // Auto-join sACN multicast group for newly discovered universes
      if (protocol === 'sacn' && !existing) {
        try { udpSocket.addMembership(sacnMulticast(universe)); } catch (_) {}
      }

      universeMap.set(universe, {
        lastSeen:   Date.now(),
        sourceName: sourceName || existing?.sourceName || '',
        channels,
      });
    });

    udpSocket.on('error', (err) => {
      console.error('[Network] UDP error:', err.message);
    });

    udpSocket.bind(port, '0.0.0.0', () => {
      if (protocol === 'sacn') {
        // Join universe discovery multicast group
        try { udpSocket.addMembership('239.255.255.250'); } catch (_) {}
      } else {
        try { udpSocket.setBroadcast(true); } catch (_) {}
      }
      console.log(`[Network] Listening for ${protocol.toUpperCase()} on port ${port}`);
    });

    // Universe list heartbeat — every 500 ms, lightweight
    universeListTimer = setInterval(() => {
      if (!mainWindow || mainWindow.isDestroyed()) return;
      const now    = Date.now();
      const active = [];
      for (const [universe, data] of universeMap) {
        if (now - data.lastSeen < 5000) {
          active.push({ universe, sourceName: data.sourceName });
        }
      }
      active.sort((a, b) => a.universe - b.universe);
      mainWindow.webContents.send('network:universes', active);
    }, 500);

    // Channel data for the subscribed universe only — ~15 fps
    channelTimer = setInterval(() => {
      if (!mainWindow || mainWindow.isDestroyed()) return;
      if (subscribedUniverse === null) return;
      const data = universeMap.get(subscribedUniverse);
      if (!data) return;
      mainWindow.webContents.send('network:channels', {
        universe: subscribedUniverse,
        channels: Array.from(data.channels),
      });
    }, 67);
  });

  ipcMain.on('network:stop', () => {
    if (udpSocket)         { try { udpSocket.close(); } catch (_) {} udpSocket = null; }
    if (universeListTimer) { clearInterval(universeListTimer); universeListTimer = null; }
    if (channelTimer)      { clearInterval(channelTimer);      channelTimer = null; }
    universeMap.clear();
    subscribedUniverse = null;
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('network:universes', []);
    }
  });

  ipcMain.on('network:subscribe',   (_, universe) => { subscribedUniverse = universe; });
  ipcMain.on('network:unsubscribe', ()            => { subscribedUniverse = null; });
}

// ── Start Flask ───────────────────────────────────────────────────────────────
function startFlask() {
  flaskProcess = spawn(PYTHON, ['run_desktop.py'], {
    cwd: BACKEND,
    windowsHide: true,
    env: {
      ...process.env,
      FIVE12_PORT:       String(PORT),
      FIVE12_STATIC_DIR: STATIC_DIR,
    },
  });

  flaskProcess.stdout.on('data', d => process.stdout.write('[Flask] ' + d));
  flaskProcess.stderr.on('data', d => process.stderr.write('[Flask] ' + d));
  flaskProcess.on('exit', code => console.log(`[Flask] exited (${code})`));
}

// ── Wait until Flask is accepting connections ─────────────────────────────────
function waitForFlask() {
  return new Promise(resolve => {
    const try_ = () => {
      http.get(`http://127.0.0.1:${PORT}/api/shows`, res => {
        res.resume();
        resolve();
      }).on('error', () => setTimeout(try_, 400));
    };
    try_();
  });
}

// ── Create the main window ────────────────────────────────────────────────────
function createWindow() {
  mainWindow = new BrowserWindow({
    width:    1440,
    height:   900,
    minWidth: 1024,
    minHeight:640,
    title:    'Five12 Lighting',
    webPreferences: {
      nodeIntegration:  false,
      contextIsolation: true,
      preload:          path.join(__dirname, 'preload.js'),
    },
    show: false,
  });

  mainWindow.loadURL(`http://127.0.0.1:${PORT}`);

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
    mainWindow.focus();
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });
}

// ── App lifecycle ─────────────────────────────────────────────────────────────
app.whenReady().then(async () => {
  setupNetworkIPC();
  console.log('[Five12] Starting Flask…');
  startFlask();
  await waitForFlask();
  console.log('[Five12] Flask ready — opening window');
  createWindow();
});

app.on('window-all-closed', () => {
  if (udpSocket)      { try { udpSocket.close(); } catch (_) {} }
  if (flaskProcess)   { flaskProcess.kill(); flaskProcess = null; }
  app.quit();
});
