/* frontend/src/app/layout.tsx - Kök Düzen */

import "./globals.css";
import type { RootLayoutProps } from "next/app";

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html lang="tr">
      <body className="min-h-screen bg-background text-foreground">{children}</body>
    </html>
  );
}

/* frontend/src/app/globals.css - Global Stiller */

@tailwind base;
@tailwind components;
@tailwind utilities;

/* frontend/src/app/components/CodeDisplay.tsx - Kod görüntüleme bileşeni */

"use client";

import { useState } from "react";

export function CodeDisplay({ code }: { code: string }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-lg border bg-card p-6 shadow-sm">
      <button 
        onClick={() => setExpanded(!expanded)}
        className="w-full text-left text-sm font-medium text-primary hover:underline mb-3"
      >
        Üretilen Kodu Görüntüle ({code.split('\n').length} satır)
      </button>
      
      {expanded && (
        <pre 
          className="bg-muted p-4 rounded-sm overflow-x-auto text-sm font-mono text-muted-foreground"
        >
          {code}
        </pre>
      )}
    </div>
  );
}

/* frontend/src/app/components/PromptBuilder.tsx - Görsel prompt oluşturucu */

"use client";

import { useState } from "react";

export function PromptBuilder() {
  const [subject, setSubject] = useState("");
  const [environment, setEnvironment] = useState("");
  const [camera, setCamera] = useState("");
  const [style, setStyle] = useState("cinematic");

  const generatePrompt = () => {
    if (!subject || !environment || !camera) {
      alert("Lütfen tüm prompt alanlarını doldurun");
      return;
    }
    
    // Profesyonel prompt oluştur
    const finalPrompt = `${subject}, ${environment}, ${camera}, ${style} style, --ar 16:9 --style raw --v 6.0`;
    
    // Panoya kopyala
    navigator.clipboard.writeText(finalPrompt);
    alert("Prompt panoya kopyalandı! ✅\n\n" + finalPrompt);
  };

  return (
    <div className="space-y-4">
      {/* Özne Bölümü */}
      <div>
        <label className="block text-sm font-medium mb-1">Özne (Subject)</label>
        <textarea
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          placeholder="Detaylı anatomik, dokusal ve çevresel tanım"
          rows={3}
          className="w-full border rounded-md px-3 py-2 focus:outline-none focus:ring-primary"
        />
      </div>

      {/* Çevre & Işık Bölümü */}
      <div>
        <label className="block text-sm font-medium mb-1">Çevre & Işık (Environment & Lighting)</label>
        <textarea
          value={environment}
          onChange={(e) => setEnvironment(e.target.value)}
          placeholder="Hacimsel aydınlatma, küresel ışıma, altın saat, stüdyo softbox"
          rows={3}
          className="w-full border rounded-md px-3 py-2 focus:outline-none focus:ring-primary"
        />
      </div>

      {/* Kamera & Lens Bölümü */}
      <div>
        <label className="block text-sm font-medium mb-1">Kamera & Lens (Camera & Lens)</label>
        <textarea
          value={camera}
          onChange={(e) => setCamera(e.target.value)}
          placeholder="35mm lens, f/1.8 diyafram, sinematik alan derinliği, makro çekim"
          rows={3}
          className="w-full border rounded-md px-3 py-2 focus:outline-none focus:ring-primary"
        />
      </div>

      {/* Stil Seçimi */}
      <div>
        <label className="block text-sm font-medium mb-1">Stil</label>
        <select
          value={style}
          onChange={(e) => setStyle(e.target.value)}
          className="w-full border rounded-md px-3 py-2 focus:outline-none focus:ring-primary"
        >
          <option value="cinematic">Sinematik</option>
          <option value="realistic">Gerçekçi</option>
          <option value="conceptual">Kavramsal</option>
          <option value="minimalist">Minimalist</option>
        </select>
      </div>

      {/* Üret Butonu */}
      <button 
        onClick={generatePrompt}
        className="w-full px-6 py-3 bg-primary text-white rounded-md font-medium hover:bg-primary/90 transition-colors"
      >
        Profesyonel Prompt Üret (Panoya Kopyala)
      </button>
    </div>
  );
}