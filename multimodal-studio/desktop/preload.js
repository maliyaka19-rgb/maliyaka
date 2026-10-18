/**
 * preload.js — Electron ana süreci ile arayüz arasında güvenli köprü.
 * contextIsolation açık olduğu için pencereye yalnızca okunabilir bilgiler
 * aktarılır; Node API'leri doğrudan verilmez.
 */
"use strict";

const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("nexusDesktop", {
  isDesktop: true,
  backendUrl: process.env.MCS_BACKEND_URL || "http://localhost:8000",
  platform: process.platform,
  versions: {
    electron: process.versions.electron,
    chrome: process.versions.chrome,
    node: process.versions.node,
  },
});
