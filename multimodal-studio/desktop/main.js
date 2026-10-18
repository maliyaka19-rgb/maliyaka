/**
 * main.js — NEXUS-CORE masaüstü (Electron) ana süreci.
 *
 * Yaptıkları:
 *  1. `multimodal-studio/` klasörünü küçük bir yerel HTTP sunucusuyla yayınlar
 *     (sohbet.html, js/, css/, chat.html, telegram.html).
 *  2. Python backend'i (`backend/run_server.py`) mümkünse otomatik başlatır;
 *     zaten çalışıyorsa (port 8000 dolu) dokunmaz.
 *  3. Arayüzü bir Electron penceresinde açar; dış bağlantılar sistem
 *     tarayıcısında açılır; motor yoksa kullanıcıya net bir uyarı gösterir.
 */
"use strict";

const { app, BrowserWindow, shell, Menu, dialog } = require("electron");
const path = require("path");
const fs = require("fs");
const net = require("net");
const { spawn, spawnSync } = require("child_process");
const { createStaticServer } = require("./static-server");

const ROOT = app.isPackaged
  ? path.join(process.resourcesPath, "studio") // paketlenmiş: extraResources -> resources/studio
  : path.resolve(__dirname, ".."); // geliştirme: multimodal-studio/
const BACKEND_DIR = path.join(ROOT, "backend");
const BACKEND_URL = process.env.MCS_BACKEND_URL || "http://localhost:8000";
const DESIRED_STATIC_PORT = Number(process.env.MCS_STATIC_PORT || 8090);

let mainWindow = null;
let backendProc = null;
let staticInfo = null;

function portInUse(port, cb) {
  const s = net.createConnection({ host: "127.0.0.1", port });
  s.once("connect", () => { s.destroy(); cb(true); });
  s.once("error", () => { cb(false); });
}

function findPython() {
  const candidates = ["python", "py", "python3"];
  for (const c of candidates) {
    try {
      const r = spawnSync(c, ["--version"], { encoding: "utf8", timeout: 5000 });
      if (!r.error && r.status === 0) return c;
    } catch (_) { /* dene */ }
  }
  return null;
}

function startBackendIfNeeded() {
  if (process.env.MCS_SKIP_BACKEND === "1") return;
  portInUse(8000, (busy) => {
    if (busy) {
      console.log("[desktop] backend zaten calisiyor (8000)");
      return;
    }
    const runServer = path.join(BACKEND_DIR, "run_server.py");
    if (!fs.existsSync(runServer)) {
      console.warn("[desktop] run_server.py bulunamadi:", runServer);
      return;
    }
    const python = findPython();
    if (!python) {
      console.warn("[desktop] python bulunamadi; backend elle baslatilmali");
      return;
    }
    console.log("[desktop] backend baslatiliyor:", python, runServer);
    backendProc = spawn(python, [runServer], {
      cwd: BACKEND_DIR,
      env: { ...process.env, PYTHONIOENCODING: "utf-8" },
      windowsHide: true,
    });
    backendProc.stdout.on("data", (d) => process.stdout.write("[backend] " + d));
    backendProc.stderr.on("data", (d) => process.stderr.write("[backend] " + d));
    backendProc.on("exit", (code) => console.log("[desktop] backend cikti:", code));
  });
}

function buildMenu(win) {
  const template = [
    {
      label: "Dosya",
      submenu: [
        { role: "reload", label: "Yenile" },
        { role: "forceReload", label: "Zorla Yenile" },
        { type: "separator" },
        { role: "quit", label: "Çıkış" },
      ],
    },
    {
      label: "Görünüm",
      submenu: [
        { role: "resetZoom", label: "Yakınlaştırmayı Sıfırla" },
        { role: "zoomIn", label: "Yakınlaştır" },
        { role: "zoomOut", label: "Uzaklaştır" },
        { type: "separator" },
        { role: "togglefullscreen", label: "Tam Ekran" },
        { role: "toggleDevTools", label: "Geliştirici Araçları" },
      ],
    },
    {
      label: "Yardım",
      submenu: [
        {
          label: "Backend durumu",
          click: async () => {
            const ok = await fetch(BACKEND_URL + "/health").then((r) => r.ok).catch(() => false);
            dialog.showMessageBox(win, {
              type: ok ? "info" : "warning",
              title: "Backend durumu",
              message: ok ? "Motor çalışıyor (port 8000)." : "Motora ulaşılamıyor (port 8000).",
              detail: BACKEND_URL,
            });
          },
        },
        { label: "NEXUS-CORE hakkında", click: () => shell.openExternal("https://github.com/") },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

async function createWindow(url) {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 940,
    minHeight: 640,
    backgroundColor: "#F8FAFC",
    title: "NEXUS-CORE",
    autoHideMenuBar: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  buildMenu(mainWindow);

  // Dış bağlantılar (telegram, github ...) sistem tarayıcısında açılsın.
  mainWindow.webContents.setWindowOpenHandler(({ url: target }) => {
    if (!target.startsWith("http://127.0.0.1") && !target.startsWith("http://localhost")) {
      shell.openExternal(target);
      return { action: "deny" };
    }
    return { action: "allow" };
  });

  await mainWindow.loadURL(url);
  mainWindow.on("closed", () => { mainWindow = null; });
}

app.whenReady().then(async () => {
  // Statik arayüz sunucusu (port doluysa otomatik boş port).
  try {
    staticInfo = await createStaticServer(ROOT, { port: DESIRED_STATIC_PORT });
  } catch (e) {
    staticInfo = await createStaticServer(ROOT, { port: 0 });
  }
  console.log(`[desktop] arayuz: http://${staticInfo.host}:${staticInfo.port}/sohbet.html`);

  startBackendIfNeeded();
  await createWindow(`http://${staticInfo.host}:${staticInfo.port}/sohbet.html`);

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow(`http://${staticInfo.host}:${staticInfo.port}/sohbet.html`);
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  if (backendProc && !backendProc.killed) {
    try { backendProc.kill(); } catch (_) {}
  }
});
