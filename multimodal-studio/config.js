/* NEXUS-CORE — dağıtım (deployment) yapılandırması
 * ---------------------------------------------------------------------------
 * Yerelde HİÇBİR ŞEY yapmanıza gerek yoktur: arayüz, backend'i (FastAPI)
 * aynı makinenin 8000 portunda arar -> http://localhost:8000
 *
 * Ücretsiz bir hosting'e dağıttığınızda backend farklı bir adreste olacağı
 * için aşağıdaki satırı doldurun, örneğin:
 *
 *     window.NEXUS_API_BASE = "https://nexus-core-backend.onrender.com";
 *
 * Boş bırakılırsa otomatik algılanır:
 *   - Sayfa 8080 (arayüz) veya 8090 (masaüstü) portundan geliyorsa backend
 *     aynı makinede `:8000` kabul edilir.
 *   - Aksi halde (backend arayüzü de servis ediyorsa: yerel 8000, tünel,
 *     ücretsiz hosting) sayfanın kendi adresi (aynı origin) kullanılır.
 *
 * Bu dosya gizli bilgi içermez; token/anahtar BURAYA YAZILMAZ.
 */
window.NEXUS_API_BASE = window.NEXUS_API_BASE || "";
