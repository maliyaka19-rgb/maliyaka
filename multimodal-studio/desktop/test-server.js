/**
 * test-server.js — Electron'a ihtiyaç duymadan statik sunucuyu doğrular.
 * Çalıştır:  node test-server.js
 */
"use strict";

const assert = require("assert");
const path = require("path");
const { createStaticServer } = require("./static-server");

async function main() {
  const root = path.resolve(__dirname, "..");
  const info = await createStaticServer(root, { port: 0 });
  const base = `http://${info.host}:${info.port}`;
  const results = [];
  const check = async (name, fn) => {
    try {
      await fn();
      results.push({ name, ok: true });
    } catch (e) {
      results.push({ name, ok: false, error: e.message });
    }
  };

  const get = async (p) => {
    const r = await fetch(base + p);
    return { status: r.status, text: await r.text(), type: r.headers.get("content-type") };
  };

  await check("kok (/) sohbet.html'i dondurur", async () => {
    const r = await get("/");
    assert.strictEqual(r.status, 200);
    assert.ok(r.text.includes("NEXUS-CORE"), "sohbet.html icerigi bekleniyor");
    assert.ok(r.type.includes("text/html"));
  });

  await check("/sohbet.html 200 + html", async () => {
    const r = await get("/sohbet.html");
    assert.strictEqual(r.status, 200);
    assert.ok(r.text.includes("<!DOCTYPE html>"));
  });

  await check("/js/app.js dogru MIME ile gelir", async () => {
    const r = await get("/js/app.js");
    assert.strictEqual(r.status, 200);
    assert.ok(r.type.includes("javascript"), "MIME: " + r.type);
    assert.ok(r.text.includes("CHAT_API"));
  });

  await check("/css/style.css 200", async () => {
    const r = await get("/css/style.css");
    assert.strictEqual(r.status, 200);
    assert.ok(r.type.includes("css"));
  });

  await check("olmayan dosya 404", async () => {
    const r = await get("/yok-boyle-dosya.xyz");
    assert.strictEqual(r.status, 404);
  });

  await check("path traversal engellenir (403/404)", async () => {
    const r = await get("/..%2f..%2f..%2fWindows%2fwin.ini");
    assert.ok(r.status === 403 || r.status === 404, "status: " + r.status);
  });

  info.server.close();

  const passed = results.filter((r) => r.ok).length;
  for (const r of results) {
    console.log(`${r.ok ? "PASS" : "FAIL"}  ${r.name}${r.ok ? "" : "  -> " + r.error}`);
  }
  console.log(`\n${passed}/${results.length} passed`);
  process.exit(passed === results.length ? 0 : 1);
}

main().catch((e) => {
  console.error("test-server hata:", e);
  process.exit(1);
});
