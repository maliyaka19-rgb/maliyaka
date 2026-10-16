/* frontend/src/app/page.tsx - Ana Uygulama Sayfası */

import { PromptBuilder } from "@/components/PromptBuilder";
import { CodeDisplay } from "@/components/CodeDisplay";
import { useState } from "react";

export default function HomePage() {
  const [selectedModule, setSelectedModule] = useState<"code" | "visual" | "video">("visual");

  const modules = [
    {
      id: "code",
      title: "Kod Üretici",
      description: "Doğal dil → Üretime hazır kod",
      icon: "💻",
      color: "bg-blue-500",
    },
    {
      id: "visual",
      title: "Görsel Üretici",
      description: "Parametrik prompt → Midjourney/SD/DALL-E",
      icon: "🎨",
      color: "bg-purple-500",
    },
    {
      id: "video",
      title: "Video Yönetmeni",
      description: "Zaman kodu → Sinematik video promptu",
      icon: "🎬",
      color: "bg-orange-500",
    },
  ];

  const handleModuleChange = (module: string) => {
    setSelectedModule(module);
  };

  return (
    <main className="min-h-screen bg-background">
      <div className="max-w-7xl mx-auto p-4 sm:p-6">
        {/* Başlık */}
        <header className="mb-8">
          <h1 className="text-4xl sm:text-5xl font-bold text-primary mb-2">
            Çoklu Ortam Yaratıcı Stüdyo
          </h1>
          <p className="text-muted-foreground text-lg">
            NEXUS-CORE v5.0 | Kurumsal Çok Modlu Yapay Zeka Platformu
          </p>
        </header>

        {/* Modül Navigasyonu */}
        <div className="flex flex-wrap gap-3 mb-6">
          {modules.map((module) => (
            <button
              key={module.id}
              onClick={() => handleModuleChange(module.id)}
              className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                selectedModule === module.id
                  ? "bg-primary text-white"
                  : "bg-muted text-foreground hover:bg-primary/20"
              }`}
            >
              {module.icon} {module.title}
            </button>
          ))}
        </div>

        {/* Seçili Modül İçeriği */}
        <div className="bg-card rounded-xl p-6 shadow-sm">
          {selectedModule === "code" && (
            <div>
              <h2 className="text-xl font-bold mb-4">Kod Üretimi</h2>
              <p className="text-muted-foreground mb-4">
                Doğal dil açıklaması gir, üretime hazır kod al.
              </p>
              
              <div className="space-y-3">
                <label className="block text-sm font-medium mb-1">
                  Prompt (Ne tür bir kod istiyorsunuz?)
                  <textarea
                    placeholder="Örn: Kullanıcı profil bilgilerini kimlik doğrulamasıyla döndüren bir FastAPI endpoint oluştur"
                    rows={3}
                    className="w-full border rounded-md px-3 py-2 focus:outline-none focus:ring-primary resize-none"
                  /></label>
                
                <label className="block text-sm font-medium mb-1">
                  Programlama Dili
                  <select className="w-full border rounded-md px-3 py-2 focus:outline-none focus:ring-primary">
                    <option value="python">Python</option>
                    <option value="javascript">JavaScript</option>
                    <option value="typescript">TypeScript</option>
                  </select>
                </label>
                
                <label className="block text-sm font-medium mb-1">
                  Framework
                  <select className="w-full border rounded-md px-3 py-2 focus:outline-none focus:ring-primary">
                    <option value="fastapi">FastAPI</option>
                    <option value="flask">Flask</option>
                    <option value="express">Express</option>
                  </select>
                </label>
                
                <button
                  onClick={() => alert("Kod üretim endpoint: POST /api/v1/generate/code")}
                  className="w-full px-6 py-3 bg-primary text-white rounded-md font-medium hover:bg-primary/90 transition-colors mt-3"
                >
                  Kod Üret
                </button>
              </div>
            </div>
          )}

          {selectedModule === "visual" && (
            <div>
              <h2 className="text-xl font-bold mb-4">Görsel Prompt Üretici</h2>
              <p className="text-muted-foreground mb-4">
                Parametrik girişlerle profesyonel yapay zeka görsel promptu oluştur.
              </p>
              
              <PromptBuilder />
            </div>
          )}

          {selectedModule === "video" && (
            <div>
              <h2 className="text-xl font-bold mb-4">Video Yönetmeni</h2>
              <p className="text-muted-foreground mb-4">
                Zaman kodu tabanlı yönetimle sinematik video sahnesi oluştur.
              </p>
              
              <div className="space-y-4">
                <label className="block text-sm font-medium mb-1">
                  Zaman Kodu (Örn: [00:00 - 00:04])
                  <input
                    type="text"
                    placeholder="[00:00 - 00:04]"
                    className="w-full border rounded-md px-3 py-2 focus:outline-none focus:ring-primary"
                  />
                </label>
                
                <label className="block text-sm font-medium mb-1">
                  Kamera Hareketi
                  <select className="w-full border rounded-md px-3 py-2 focus:outline-none focus:ring-primary">
                    <option value="FPV drone dive">FPV Drone Dalışı</option>
                    <option value="Dolly zoom">Dolly Zoom</option>
                    <option value="Parallax pan">Paralaks Pan</option>
                    <option value="Orbit shot">Orbit Çekimi</option>
                  </select>
                </label>
                
                <label className="block text-sm font-medium mb-1">
                  Hareket Dinamiği
                  <textarea
                    placeholder="Karakter hızı, yönü, fizik etkileşimi"
                    rows={2}
                    className="w-full border rounded-md px-3 py-2 focus:outline-none focus:ring-primary resize-none"
                  /></label>
                
                <button
                  onClick={() => alert("Video üretim endpoint: POST /api/v1/generate/video")}
                  className="w-full px-6 py-3 bg-primary text-white rounded-md font-medium hover:bg-primary/90 transition-colors mt-3"
                >
                  Video Promptu Üret
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}