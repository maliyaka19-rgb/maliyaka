/**
 * static-server.js — NEXUS-CORE masaüstü uygulaması için küçük, bağımlılıksız
 * statik dosya sunucusu.
 *
 * Electron ana sürecinden çağrılır ve `multimodal-studio/` kökünü (sohbet.html,
 * js/, css/, chat.html, telegram.html ...) tarayıcıya sunar. Böylece arayüz
 * file:// yerine gerçek bir http:// kaynağından yüklenir; localStorage,
 * göreli yollar ve backend CORS'u doğru çalışır.
 *
 * Electron'a bağımlı DEĞİLDİR; bu yüzden `node test-server.js` ile ayrı test
 * edilebilir.
 */
"use strict";

const http = require("http");
const fs = require("fs");
const path = require("path");

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
  ".webp": "image/webp",
  ".mp4": "video/mp4",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".map": "application/json; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
  ".md": "text/markdown; charset=utf-8",
};

function createStaticServer(rootDir, opts = {}) {
  const root = path.resolve(rootDir);

  const server = http.createServer((req, res) => {
    try {
      const url = new URL(req.url, "http://localhost");
      let pathname = decodeURIComponent(url.pathname);
      if (pathname === "/" || pathname === "") pathname = "/sohbet.html";

      // Güvenlik: root dışına çıkmayı (path traversal) engelle.
      const target = path.resolve(root, "." + pathname);
      if (target !== root && !target.startsWith(root + path.sep)) {
        res.writeHead(403, { "Content-Type": "text/plain; charset=utf-8" });
        res.end("403 Forbidden");
        return;
      }

      fs.stat(target, (err, stat) => {
        if (err || !stat.isFile()) {
          res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
          res.end("404 Not Found");
          return;
        }
        const ext = path.extname(target).toLowerCase();
        res.writeHead(200, {
          "Content-Type": MIME[ext] || "application/octet-stream",
          "Content-Length": stat.size,
          "Cache-Control": "no-cache",
        });
        fs.createReadStream(target).pipe(res);
      });
    } catch (e) {
      res.writeHead(500, { "Content-Type": "text/plain; charset=utf-8" });
      res.end("500 " + e.message);
    }
  });

  return new Promise((resolve, reject) => {
    const port = opts.port || 0;
    const host = opts.host || "127.0.0.1";
    server.once("error", reject);
    server.listen(port, host, () => {
      const addr = server.address();
      resolve({ server, port: addr.port, host: addr.address, root });
    });
  });
}

module.exports = { createStaticServer, MIME };
