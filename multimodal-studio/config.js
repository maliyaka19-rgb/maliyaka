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
 * Boş bırakılırsa otomatik olarak `<aynı-host>:8000` kullanılır.
 * Bu dosya gizli bilgi içermez; token/anahtar BURAYA YAZILMAZ.
 */
window.NEXUS_API_BASE = window.NEXUS_API_BASE || "";
