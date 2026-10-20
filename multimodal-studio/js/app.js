/* NEXUS-CORE v6.1 — Main App (extracted from sohbet.html, Phase 3.1 modularization) */
    
        // Initialize immediately if DOM is ready, otherwise wait for DOMContentLoaded
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', initApp);
        } else {
            initApp();
        }

        function initApp() {
        'use strict';

        // Backend kök adresi. Öncelik: `window.NEXUS_API_BASE` (config.js) >
        // otomatik algılama.
        //
        // Otomatik kural:
        //  - Sayfa kendi statik geliştirme sunucumuzdan geliyorsa (8080 arayüz,
        //    8090 masaüstü) backend aynı makinede 8000 portundadır.
        //  - Aksi halde (backend arayüzü de servis ediyor: yerel 8000, tünel,
        //    ücretsiz hosting) AYNI ORIGIN kullanılır. Bu sayede tünel/hosting
        //    adresinde `:8000` gibi geçersiz bir adres üretilmez.
        const _STATIC_DEV_PORTS = ['8080', '8090'];
        const API_BASE = (
            (typeof window !== 'undefined' && window.NEXUS_API_BASE)
            || (_STATIC_DEV_PORTS.indexOf(location.port) !== -1
                ? `${location.protocol}//${location.hostname}:8000`
                : location.origin)
            || `${location.protocol}//${location.hostname || 'localhost'}:8000`
        ).replace(/\/+$/, '');

        const CHAT_API = `${API_BASE}/api/v1/ai/chat`;
        const AUTH_API = `${API_BASE}/api/v1/auth`;
        const MODELS_API = `${API_BASE}/api/v1/models`;
        // Görseller backend proxy'sinden (mutlak URL) yüklenir.
        const IMAGE_PROXY_API = `${API_BASE}/api/v1/image/proxy`;
        // Proje/dosya ve dosya sistemi uç noktaları (dosya ağacı, editör, proje tarayıcı).
        const PROJECT_API = `${API_BASE}/api/v1/project`;
        const FS_API = `${API_BASE}/api/v1/fs`;

        // ===== STATE =====
        let token = null;
        let currentUser = null;
        let convId = null;
        let currentChatId = null;
        let busy = false;
        let isNewUser = false;

        // ===== DOM ELEMENTS =====
        const sidebar = document.getElementById('sidebar');
        const overlay = document.getElementById('sidebar-overlay');
        const msgs = document.getElementById('messages');
        const inp = document.getElementById('message-input');
        const sendBtn = document.getElementById('send-btn');
        const welcome = document.getElementById('welcome');
        const chatTitle = document.getElementById('chat-title');
        const chatList = document.getElementById('chat-list');

        // ===== THEME (light varsayılan, localStorage'da saklanır) =====
        const themeToggleBtn = document.getElementById('theme-toggle');
        let currentTheme = localStorage.getItem('nexus_theme') || 'light';

        function applyTheme(theme) {
            document.documentElement.setAttribute('data-theme', theme);
            if (themeToggleBtn) themeToggleBtn.textContent = theme === 'dark' ? '☀️' : '🌙';
        }
        applyTheme(currentTheme);

        if (themeToggleBtn) {
            themeToggleBtn.addEventListener('click', () => {
                currentTheme = currentTheme === 'dark' ? 'light' : 'dark';
                localStorage.setItem('nexus_theme', currentTheme);
                applyTheme(currentTheme);
            });
        }

        // ===== MOBILE SIDEBAR =====
        const sidebarOverlay = document.getElementById('sidebar-overlay');
        const menuToggleBtn = document.getElementById('menu-toggle');

        function openSidebar() {
            sidebar.classList.add('open');
            if (sidebarOverlay) sidebarOverlay.classList.add('active');
        }
        function closeSidebar() {
            sidebar.classList.remove('open');
            if (sidebarOverlay) sidebarOverlay.classList.remove('active');
        }
        if (menuToggleBtn) menuToggleBtn.addEventListener('click', openSidebar);
        if (sidebarOverlay) sidebarOverlay.addEventListener('click', closeSidebar);

        // ===== HELPERS =====
        function $(sel){ return document.querySelector(sel); }
        function $$(sel){ return document.querySelectorAll(sel); }
        function escapeHtml(s){
            const div = document.createElement('div');
            div.textContent = s;
            return div.innerHTML;
        }
        function formatDate(iso){
            try {
                return new Date(iso).toLocaleString('tr-TR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
            } catch { return iso; }
        }

        // ===== API CALL =====
        async function apiCall(path, method, body) {
            const headers = { 'Content-Type': 'application/json' };
            if (token) headers['Authorization'] = `Bearer ${token}`;
            const response = await fetch(AUTH_API + path, {
                method,
                headers,
                body: body ? JSON.stringify(body) : undefined
            });
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.detail || 'Bir hata oluştu');
            }
            return data;
        }

        // ===== INITIALIZE SESSION =====
        function initSession() {
            token = localStorage.getItem('nexus_token');
            if (token) {
                validateToken();
            } else {
                window.location.href = '/chat.html';
            }
        }

        async function validateToken() {
            try {
                const user = await apiCall('/me', 'GET');
                currentUser = user;
                currentUser.isGuest = false;
                showApp();
            } catch (err) {
                if (token.startsWith('guest_')) {
                    currentUser = { id: token, username: 'Misafir', email: 'guest@local', isGuest: true };
                    showApp();
                } else {
                    localStorage.removeItem('nexus_token');
                    window.location.href = '/chat.html';
                }
            }
        }

        // ===== SHOW APP =====
        function showApp() {
            if (!currentUser?.isGuest) {
                loadChats();
                // Update user info in sidebar
                const username = currentUser.username || currentUser.email?.split('@')[0] || 'Kullanıcı';
                const firstLetter = username.charAt(0).toUpperCase();
                document.getElementById('user-avatar').textContent = firstLetter;
                document.getElementById('user-name').textContent = username;
                document.getElementById('user-email').textContent = currentUser.email || '';
            } else {
                loadGuestChats();
                document.getElementById('user-avatar').textContent = 'M';
                document.getElementById('user-name').textContent = 'Misafir';
                document.getElementById('user-email').textContent = 'guest@local';
            }
            inp.disabled = false;
            sendBtn.disabled = false;
        }

        // ===== LOGOUT =====
        function logout() {
            token = null;
            currentUser = null;
            convId = null;
            currentChatId = null;
            localStorage.removeItem('nexus_token');
            window.location.href = '/chat.html';
        }
        $('#logout-btn').addEventListener('click', logout);

        // ===== LOAD CHATS =====
        async function loadChats() {
            try {
                const data = await apiCall('/chats', 'GET');
                renderChatList(data.chats || []);
            } catch (e) {
                console.error('Sohbetler yüklenemedi:', e);
            }
        }

        function loadGuestChats() {
            try {
                const stored = localStorage.getItem('guest_chats');
                let chats = stored ? JSON.parse(stored) : [];
                
                // Clean up old chats with default titles and no messages
                chats = chats.filter(c => {
                    if (c.messages && c.messages.length > 0) return true;
                    if (c.title && c.title !== 'Yeni Sohbet') return true;
                    return false;
                });
                
                renderGuestChatList(chats);
            } catch (e) {
                console.error('Guest chats error:', e);
                renderGuestChatList([]);
            }
        }

        function saveGuestChats(chats) {
            localStorage.setItem('guest_chats', JSON.stringify(chats));
        }

        function renderChatList(chats) {
            if (!chats || !chats.length) {
                chatList.innerHTML = '<div class="empty-chats"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>Henüz sohbet yok<br><span style="font-size:.7rem">"Yeni" butonuyla başlayın</span></div>';
                return;
            }
            chatList.innerHTML = chats.map(c => `
                <div class="chat-item ${c.id === currentChatId ? 'active' : ''}" data-id="${c.id}">
                    <div class="chat-item-title">${escapeHtml(c.title)}</div>
                    <div class="chat-item-meta"><span>${c.message_count || 0} mesaj</span><span>${formatDate(c.updated_at)}</span></div>
                    <div class="chat-item-actions">
                        <button class="chat-action-btn rename-btn" data-id="${c.id}" title="Yeniden adlandır">✏️</button>
                        <button class="chat-action-btn delete-btn" data-id="${c.id}" title="Sil">🗑️</button>
                    </div>
                </div>
            `).join('');

            chatList.querySelectorAll('.chat-item').forEach(el => {
                el.addEventListener('click', e => {
                    if (!e.target.closest('.chat-action-btn')) {
                        selectChat(el.dataset.id);
                    }
                });
            });
            chatList.querySelectorAll('.rename-btn').forEach(btn => {
                btn.addEventListener('click', e => { e.stopPropagation(); renameChat(btn.dataset.id); });
            });
            chatList.querySelectorAll('.delete-btn').forEach(btn => {
                btn.addEventListener('click', e => { e.stopPropagation(); deleteChat(btn.dataset.id); });
            });
        }

        function renderGuestChatList(chats) {
            if (!chats || !chats.length) {
                chatList.innerHTML = '<div class="empty-chats"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>Misafir modu — geçici sohbetler<br><span style="font-size:.7rem">Tarayıcı kapatılırsa kaybolur</span></div>';
                return;
            }
            // Sort by updated_at descending (newest first)
            chats.sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at));
            
            chatList.innerHTML = chats.map(c => {
                const title = c.title && c.title !== 'Yeni Sohbet' ? c.title : 'Yeni Sohbet';
                const msgCount = c.messages ? c.messages.length : 0;
                return `
                <div class="chat-item ${c.id === currentChatId ? 'active' : ''}" data-id="${c.id}">
                    <div class="chat-item-title">${escapeHtml(title)}</div>
                    <div class="chat-item-meta"><span>${msgCount} mesaj</span><span>${formatDate(c.updated_at)}</span></div>
                    <div class="chat-item-actions">
                        <button class="chat-action-btn delete-btn" data-id="${c.id}" title="Sil">🗑️</button>
                    </div>
                </div>
            `;
            }).join('');

            chatList.querySelectorAll('.chat-item').forEach(el => {
                el.addEventListener('click', e => {
                    if (!e.target.closest('.chat-action-btn')) {
                        selectGuestChat(el.dataset.id);
                    }
                });
            });
            chatList.querySelectorAll('.delete-btn').forEach(btn => {
                btn.addEventListener('click', e => { e.stopPropagation(); deleteGuestChat(btn.dataset.id); });
            });
        }

        // ===== SELECT CHAT =====
        async function selectChat(id) {
            currentChatId = id;
            convId = id;
            document.querySelectorAll('.chat-item').forEach(el => {
                el.classList.toggle('active', el.dataset.id === id);
            });
            try {
                const data = await apiCall(`/chats/${id}`, 'GET');
                chatTitle.textContent = data.title || 'Sohbet';
                // Load messages from the chat
                msgs.innerHTML = '';
                if (data.messages && data.messages.length > 0) {
                    welcome.classList.add('hidden');
                    data.messages.forEach(m => {
                        if (m.role === 'user') addMsg('user', escapeHtml(m.content), false);
                        else if (m.role === 'assistant') addMsg('assistant', md(m.content));
                    });
                    msgs.scrollTop = msgs.scrollHeight;
                } else {
                    welcome.classList.remove('hidden');
                }
                closeSidebar();
                inp.focus();
            } catch (e) {
                console.error('Sohbet seçilemedi:', e);
            }
        }

        function selectGuestChat(id) {
            currentChatId = id;
            convId = id;
            document.querySelectorAll('.chat-item').forEach(el => {
                el.classList.toggle('active', el.dataset.id === id);
            });
            const stored = localStorage.getItem('guest_chats');
            const chats = stored ? JSON.parse(stored) : [];
            const chat = chats.find(c => c.id === id);
            if (chat) {
                chatTitle.textContent = chat.title || 'Sohbet';
                loadGuestMessages(chat);
                closeSidebar();
                inp.focus();
            }
        }

        // ===== CHAT OPERATIONS =====
        async function createNewChat() {
            if (currentUser?.isGuest) {
                const convId = 'guest_' + Date.now().toString(36);
                const chat = { id: convId, title: 'Yeni Sohbet', messages: [], created_at: new Date().toISOString(), updated_at: new Date().toISOString() };
                const stored = localStorage.getItem('guest_chats');
                const chats = stored ? JSON.parse(stored) : [];
                chats.unshift(chat);
                saveGuestChats(chats);
                loadGuestChats();
                selectGuestChat(convId);
                return;
            }
            try {
                const data = await apiCall('/chats', 'POST', { title: 'Yeni Sohbet' });
                await loadChats();
                await selectChat(data.id);
            } catch (e) {
                console.error('Sohbet oluşturulamadı:', e);
            }
        }
        $('#new-chat-btn').addEventListener('click', createNewChat);

        async function renameChat(id) {
            const newTitle = prompt('Yeni sohbet başlığı:');
            if (!newTitle || !newTitle.trim()) return;
            try {
                await apiCall(`/chats/${id}`, 'PATCH', { title: newTitle.trim() });
                loadChats();
            } catch (e) {
                alert('Güncellenemedi: ' + e.message);
            }
        }

        async function deleteChat(id) {
            if (!confirm('Bu sohbeti silmek istediğinizden emin misiniz?')) return;
            try {
                await apiCall(`/chats/${id}`, 'DELETE');
                if (id === currentChatId) {
                    currentChatId = null; convId = null;
                    chatTitle.textContent = 'Yeni Sohbet';
                    welcome.classList.remove('hidden');
                    msgs.innerHTML = '';
                }
                loadChats();
            } catch (e) {
                alert('Silinemedi: ' + e.message);
            }
        }

        // ===== GUEST CHAT OPERATIONS =====
        function deleteGuestChat(id) {
            if (!confirm('Bu sohbeti silmek istediğinizden emin misiniz?')) return;
            const stored = localStorage.getItem('guest_chats');
            const chats = stored ? JSON.parse(stored) : [];
            const filtered = chats.filter(c => c.id !== id);
            saveGuestChats(filtered);
            if (id === currentChatId) {
                currentChatId = null; convId = null;
                chatTitle.textContent = 'Yeni Sohbet';
                welcome.classList.remove('hidden');
                msgs.innerHTML = '';
            }
            loadGuestChats();
        }

        // ===== SEND MESSAGE =====
        inp.addEventListener('input', () => {
            inp.style.height = 'auto';
            inp.style.height = Math.min(inp.scrollHeight, 180) + 'px';
        });

        inp.addEventListener('keydown', e => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMsg();
            }
        });

        sendBtn.addEventListener('click', sendMsg);

        // Upload dropdown toggle
        $('#upload-btn').addEventListener('click', (e) => {
            e.stopPropagation();
            $('#upload-dropdown').style.display = $('#upload-dropdown').style.display === 'block' ? 'none' : 'block';
        });

        // Close dropdown when clicking outside
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.upload-wrapper')) {
                $('#upload-dropdown').style.display = 'none';
            }
        });

        // File upload from dropdown
        $('#upload-file').addEventListener('click', () => {
            $('#file-input').click();
            $('#upload-dropdown').style.display = 'none';
        });

        // Video upload from dropdown
        $('#upload-video').addEventListener('click', () => {
            $('#video-input').click();
            $('#upload-dropdown').style.display = 'none';
        });

        // Image upload from dropdown
        $('#upload-image').addEventListener('click', () => {
            $('#image-input').click();
            $('#upload-dropdown').style.display = 'none';
        });

        // File upload handler
        $('#file-input').addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if (!file) return;
            inp.value = `Dosya yüklendi: ${file.name}. İçeriğini oku ve analiz et.`;
            sendMsg();
        });

        // Video upload handler
        $('#video-input').addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if (!file) return;
            inp.value = `Video yüklendi: ${file.name}. Bu videoyu analiz et ve özetle.`;
            sendMsg();
        });

        // Image upload handler
        $('#image-input').addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if (!file) return;
            inp.value = `Görsel yüklendi: ${file.name}. Bu görseli analiz et ve açıkla.`;
            sendMsg();
        });

        $('#suggestions').addEventListener('click', e => {
            const btn = e.target.closest('.sugg');
            if (btn && btn.dataset.q) {
                inp.value = btn.dataset.q;
                sendMsg();
            }
        });

        function addMsg(role, html, isHtml = true) {
            const div = document.createElement('div');
            div.className = 'msg ' + (role === 'user' ? 'user' : 'assistant');
            const av = role === 'user' ? '👤' : '🤖';
            div.innerHTML = `<div class="avatar">${av}</div><div class="bubble">${isHtml ? html : escapeHtml(html)}</div>`;
            msgs.appendChild(div);
            msgs.scrollTop = msgs.scrollHeight;
            return div;
        }

        function addTyping() {
            const div = document.createElement('div');
            div.className = 'msg assistant typing-msg';
            div.innerHTML = `<div class="bubble"><span></span><span></span><span></span></div>`;
            msgs.appendChild(div);
            msgs.scrollTop = msgs.scrollHeight;
            return div;
        }

        function removeTyping() {
            $$('.typing-msg').forEach(e => e.remove());
        }

        // ============================================================
        // LIVE STATUS INDICATOR - Shows what AI is doing in real-time
        // ============================================================
        let statusInterval = null;
        
        function addLiveStatus(txt) {
            // MASTER PROMPT §13: gerçek ilerleme bilgisi olmadan sahte yüzde
            // gösterme. Belirsiz (indeterminate) bir "çalışıyor" göstergesi kullan.
            removeTyping();
            const div = document.createElement('div');
            div.className = 'typing-msg';
            div.innerHTML = `
                <div class="live-status" id="live-status">
                    <div class="live-status-steps">
                        <div class="live-step active">
                            <span class="live-step-icon">🤖</span>
                            <span class="live-step-text">Düşünüyor...</span>
                        </div>
                    </div>
                    <div class="live-status-progress indeterminate" aria-hidden="true">
                        <div class="live-progress-bar"></div>
                    </div>
                </div>
            `;
            msgs.appendChild(div);
            msgs.scrollTop = msgs.scrollHeight;
            return div;
        }
        
        function removeLiveStatus() {
            if (statusInterval) {
                clearInterval(statusInterval);
                statusInterval = null;
            }
            $$('.typing-msg').forEach(e => e.remove());
        }

        // --- Görsel yardımcıları (markdown ![]() ve çıplak pollinations URL'leri) ---
        function proxyImageUrl(url) {
            return /^https:\/\/image\.pollinations\.ai\//.test(url)
                ? IMAGE_PROXY_API + '?url=' + encodeURIComponent(url)
                : url;
        }

        function renderImage(url, alt) {
            const src = proxyImageUrl(url);
            const label = (alt && alt.trim()) ? alt.trim() : 'Üretilen görsel';
            const safeAlt = label.replace(/"/g, '&quot;');
            const safeUrl = url.replace(/"/g, '&quot;');
            return '<figure class="chat-figure">'
                + '<div class="chat-figure-state">🖼️ Görsel üretiliyor… (Pollinations, birkaç saniye sürebilir)</div>'
                + '<img class="chat-image" data-src="' + src + '" src="' + src + '" alt="' + safeAlt + '" loading="eager"'
                + ' onload="chatImgLoaded(this)" onerror="chatImgError(this)">'
                + '<figcaption class="chat-figure-cap">' + safeAlt
                + ' · <a href="' + safeUrl + '" target="_blank" rel="noopener">yeni sekmede aç</a></figcaption>'
                + '</figure>';
        }

        // Inline handler'lar IIFE dışından çağrıldığı için window'a bağlanır.
        window.chatImgLoaded = function (img) {
            const fig = img.closest('.chat-figure');
            if (fig) fig.classList.add('loaded');
        };
        // Pollinations ücretsiz katmanı kısa süreli 402 (rate limit) döndürür ve
        // ~30-60 sn içinde toparlanır. Bu yüzden artan beklemeyle yeniden deneriz.
        const IMG_RETRY_DELAYS = [8000, 20000, 35000];
        window.chatImgError = function (img) {
            const fig = img.closest('.chat-figure');
            if (!fig) return;
            const n = parseInt(img.dataset.retry || '0', 10);
            const state = fig.querySelector('.chat-figure-state');
            if (n < IMG_RETRY_DELAYS.length) {
                img.dataset.retry = String(n + 1);
                const secs = Math.round(IMG_RETRY_DELAYS[n] / 1000);
                if (state) state.textContent = '⏳ Pollinations limiti; ' + secs + ' sn sonra tekrar denenecek (' + (n + 1) + '/' + IMG_RETRY_DELAYS.length + ')…';
                setTimeout(function () {
                    const sep = img.dataset.src.indexOf('?') > -1 ? '&' : '?';
                    img.src = img.dataset.src + sep + '_r=' + (n + 1);
                }, IMG_RETRY_DELAYS[n]);
            } else {
                fig.classList.add('failed');
                if (state) state.textContent = '⚠️ Görsel yüklenemedi (Pollinations ücretsiz limiti). Yukarıdaki bağlantıdan deneyin.';
            }
        };

        function md(text) {
            if (!text) return '';
            // 1) Kod bloklarını geçici koru (içindeki URL'ler bozulmasın)
            const codeBlocks = [];
            text = text.replace(/```(\w*)\n?([\s\S]*?)```/g, (m, lang, code) => {
                codeBlocks.push('<pre><code>' + code + '</code></pre>');
                return '\u0000CB' + (codeBlocks.length - 1) + '\u0000';
            });
            // 2) Markdown görselleri: ![alt](url) -> gerçek <img>
            text = text.replace(/!\[([^\]]*)\]\((https?:\/\/[^\s)]+)\)/g, (m, alt, url) => renderImage(url, alt));
            // 3) Çıplak pollinations URL'leri (zaten dönüştürülmüş src/href'ler hariç)
            text = text.replace(/(^|[^"'=(])(https:\/\/image\.pollinations\.ai\/[^\s)"'<>]+)/g,
                (m, pre, url) => pre + renderImage(url, ''));
            // 4) Diğer markdown
            text = text.replace(/`([^`]+)`/g, '<code>$1</code>');
            text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
            text = text.replace(/\*([^*]+)\*/g, '<em>$1</em>');
            text = text.replace(/^### (.+)$/gm, '<h3>$1</h3>');
            text = text.replace(/^## (.+)$/gm, '<h2>$1</h2>');
            text = text.replace(/^# (.+)$/gm, '<h1>$1</h1>');
            text = text.replace(/^[-•] (.+)$/gm, '<li>$1</li>');
            text = text.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
            text = text.replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>');
            text = text.replace(/\n\n/g, '</p><p>');
            text = text.replace(/\n/g, '<br>');
            // 5) Kod bloklarını geri koy
            text = text.replace(/\u0000CB(\d+)\u0000/g, (m, i) => codeBlocks[parseInt(i, 10)]);
            return '<p>' + text + '</p>';
        }

        function buildThinkingSteps(steps) {
            if (!steps?.length) return '';
            
            const stepsHtml = steps.map((step, i) => `
                <div class="thinking-step ${step.type}" style="animation-delay: ${i * 0.1}s">
                    <span class="thinking-step-icon">${step.icon || '💭'}</span>
                    <span class="thinking-step-content">${escapeHtml(step.content)}</span>
                </div>
            `).join('');
            
            return `
                <div class="thinking-steps" id="thinking-${Date.now()}">
                    <div class="thinking-steps-header">
                        <span>🧠 Düşünce Süreci</span>
                        <button class="thinking-steps-toggle" onclick="this.parentElement.parentElement.classList.toggle('collapsed')">Gizle/Göster</button>
                    </div>
                    ${stepsHtml}
                </div>
            `;
        }
        
        async function sendMsg() {
            if (busy || !inp.value.trim()) return;
            const txt = inp.value.trim();
            inp.value = '';
            inp.style.height = 'auto';
            welcome.classList.add('hidden');
            addMsg('user', txt, false);
            busy = true;
            sendBtn.disabled = true;
            addLiveStatus(txt);  // Show live progress indicator

            try {
                const res = await fetch(CHAT_API, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': token ? `Bearer ${token}` : ''
                    },
                    body: JSON.stringify({
                        message: txt,
                        conversation_id: convId,
                        agent_id: currentAgentId
                    })
                });
                const data = await res.json();
                removeLiveStatus();

                if (data.success) {
                    convId = data.conversation_id;
                    if (!currentChatId) currentChatId = convId;
                    
                    let html = '';

                    // Ana Yönetici kodlama görevini zincire devrettiyse göster
                    if (data.coding && Array.isArray(data.coding.experts) && data.coding.experts.length) {
                        const experts = data.coding.experts.map(escapeHtml).join(' → ');
                        html += `<div style="display:block;padding:6px 10px;background:var(--bg-surface);border:1px solid var(--border);border-radius:12px;font-size:0.75rem;color:var(--fg-muted);margin-bottom:8px;">
                            🧩 ${escapeHtml(data.coding.task_type || '')} · ${data.coding.experts.length} uzman · <strong>plan</strong><br>
                            <span style="opacity:.85">${experts}</span>
                        </div><br>`;
                    }

                    // Add thinking steps if available
                    if (data.thinking_steps?.length) {
                        html += buildThinkingSteps(data.thinking_steps);
                    }
                    
                    html += md(data.response);
                    
                    // Görseller artık md() içinde gerçek <img> olarak render edilir
                    // (markdown ![]() ve çıplak pollinations URL'leri; proxy + hata/retry ile).
                    
                    // Render generated videos (.mp4) as a playable <video> (Aşama 9/13)
                    const videoUrls = [...new Set([...data.response.matchAll(/https?:\/\/[^\s)"'<>]+\.mp4/g)].map(m => m[0]))];
                    videoUrls.forEach(vu => {
                        html += `<div class="generated-video" style="margin-top:12px;border-radius:8px;overflow:hidden;border:1px solid var(--border);">
                            <video src="${vu}" controls preload="metadata" playsinline style="max-width:100%;display:block;background:#000;"></video>
                            <div style="padding:8px;font-size:0.7rem;color:var(--fg-muted);background:var(--bg-surface);border-top:1px solid var(--border);">🎥 Üretilen video</div>
                        </div>`;
                    });

                    if (data.tools_used?.length) {
                        const labels = {
                            read_file: '📖 Oku',
                            write_file: '📝 Yaz',
                            edit_file: '✏️ Düzenle',
                            list_files: '📁 Listele',
                            search_files: '🔍 Ara',
                            execute_command: '⚙️ Çalıştır',
                            generate_code: '💻 Kod',
                            generate_visual_prompt: '🎨 Görsel Prompt',
                            generate_image: '🖼️ Görsel Üret',
                            generate_video_prompt: '🎬 Video Prompt',
                            generate_real_video: '🎥 Gerçek Video',
                            answer_question: '💬 Cevap',
                            web_search: '🔍 Arama',
                            search_learning: '🧠 Öğrenme'
                        };
                        const badges = data.tools_used.map(t => `<span class="tool">${labels[t] || t}</span>`).join('');
                        html = `<div class="tools">${badges}</div>` + html;
                    }
                    addMsg('assistant', html);
                    
                    // Save chat AFTER adding both messages to DOM
                    if (!currentUser?.isGuest) {
                        loadChats();
                    } else {
                        saveGuestChat(data.conversation_id);
                        loadGuestChats();
                    }
                } else {
                    addMsg('assistant', escapeHtml('Hata: ' + (data.error || 'Bilinmeyen hata')), false);
                }
            } catch (e) {
                removeLiveStatus();
                addMsg('assistant', escapeHtml('Bağlantı hatası: Sunucuya erişilemedi. Backend çalışıyor mu?'), false);
            }
            busy = false;
            sendBtn.disabled = false;
            inp.focus();
        }

        function saveGuestChat(convId) {
            const stored = localStorage.getItem('guest_chats');
            const chats = stored ? JSON.parse(stored) : [];
            const allMsgs = msgs.querySelectorAll('.msg');
            const messages = [];
            allMsgs.forEach(m => {
                const role = m.classList.contains('user') ? 'user' : 'assistant';
                const content = m.querySelector('.bubble')?.textContent || '';
                if (content.trim()) {
                    messages.push({ role, content, timestamp: new Date().toISOString() });
                }
            });
            let chat = chats.find(c => c.id === convId);
            const firstUser = messages.find(m => m.role === 'user');
            // Use first 10 characters of first user message as title
            const title = firstUser ? firstUser.content.slice(0, 10) + (firstUser.content.length > 10 ? '...' : '') : 'Yeni Sohbet';
            const now = new Date().toISOString();
            if (chat) {
                chat.messages = messages;
                chat.updated_at = now;
                // Always update title from first user message
                if (firstUser) {
                    chat.title = title;
                }
            } else {
                chats.push({ id: convId, title, messages, created_at: now, updated_at: now });
            }
            saveGuestChats(chats);
        }

        function loadGuestMessages(chat) {
            msgs.innerHTML = '';
            if (chat.messages && chat.messages.length > 0) {
                welcome.classList.add('hidden');
                chat.messages.forEach(m => {
                    if (m.role === 'user') addMsg('user', escapeHtml(m.content), false);
                    else if (m.role === 'assistant') addMsg('assistant', md(m.content));
                });
                msgs.scrollTop = msgs.scrollHeight;
            } else {
                welcome.classList.remove('hidden');
            }
        }

        // ============================================================
        // AGENT BUILDER (Custom AI Agents)
        // ============================================================
        const AGENT_API = `${API_BASE}/api/v1/agents`;
        const agentModalOverlay = document.getElementById('agent-modal-overlay');
        const agentGridView = document.getElementById('agent-list-view');
        const agentEditor = document.getElementById('agent-editor');
        const agentGrid = document.getElementById('agent-grid');
        
        // Agent modal model provider elements - queried dynamically in functions
        // const agentProviderGrid = document.getElementById('provider-grid-agent-modal');
        // const agentApiKeyProviderSelect = document.getElementById('api-key-provider-select');
        // const agentApiKeyInput = document.getElementById('api-key-input-agent');
        // const agentApiKeySave = document.getElementById('api-key-save-agent');
        // const agentApiKeyHelp = document.getElementById('api-key-help-agent');
        
        let agents = [];
        let currentAgentId = localStorage.getItem('current_agent_id') || 'main-manager';
        let editingAgentId = null;
        let selectedIcon = '🤖';
        let selectedColor = '#6366f1';
        let selectedTools = [];
        let agentModelCatalog = null;
        
        // Available tools (all NEXUS-CORE tools)
        const AVAILABLE_TOOLS = [
            // File System Tools
            { id: 'read_file', name: 'Dosya Oku', icon: '📖', group: 'Dosya' },
            { id: 'write_file', name: 'Dosya Yaz', icon: '📝', group: 'Dosya' },
            { id: 'edit_file', name: 'Dosya Düzenle', icon: '✏️', group: 'Dosya' },
            { id: 'list_files', name: 'Klasör Listele', icon: '📁', group: 'Dosya' },
            { id: 'search_files', name: 'Dosya Ara', icon: '🔍', group: 'Dosya' },
            { id: 'execute_command', name: 'Komut Çalıştır', icon: '⚙️', group: 'Dosya' },
            // AI Generation Tools
            { id: 'generate_code', name: 'Kod Üret', icon: '💻', group: 'Yapay Zeka' },
            { id: 'generate_visual_prompt', name: 'Görsel Prompt', icon: '🎨', group: 'Yapay Zeka' },
            { id: 'generate_video_prompt', name: 'Video Prompt', icon: '🎬', group: 'Yapay Zeka' },
            // Intelligence Tools
            { id: 'web_search', name: 'Web Arama', icon: '🌐', group: 'Zeka' },
            { id: 'search_learning', name: 'Öğrenme Ara', icon: '🧠', group: 'Zeka' },
            { id: 'answer_question', name: 'Soru Cevapla', icon: '💬', group: 'Zeka' }
        ];
        
        // Load agents from API
        async function loadAgents() {
            try {
                const res = await fetch(AGENT_API);
                const data = await res.json();
                if (data.success) {
                    agents = data.agents;
                    // Eski localStorage'da silinmis bir ajan veya kaldirilan
                    // 'auto'/'team' modu kalmis olabilir; Ana Yonetici'ye tasi.
                    if (!agents.some(a => a.id === currentAgentId)) {
                        currentAgentId = 'main-manager';
                        localStorage.setItem('current_agent_id', currentAgentId);
                    }
                    renderAgentGrid();
                    updateCurrentAgentDisplay();
                    updateHeaderAgentButton(currentAgentId);
                }
            } catch (e) {
                console.error('Agents load error:', e);
            }
        }
        
        // Render agent grid
        function renderAgentGrid() {
            let html = '';
            
            agents.forEach(agent => {
                const isActive = agent.id === currentAgentId;
                const toolsHtml = (agent.tools || []).map(t => {
                    const tool = AVAILABLE_TOOLS.find(at => at.id === t);
                    return tool ? `<span class="agent-tool-badge">${tool.icon} ${tool.name}</span>` : '';
                }).join('');
                
                html += `
                    <div class="agent-card ${isActive ? 'active' : ''}" data-id="${agent.id}" style="border-color: ${isActive ? agent.color : 'var(--border)'}">
                        <div class="agent-card-actions">
                            ${!agent.is_default ? `
                                <button class="agent-action-btn edit-btn" data-id="${agent.id}" title="Düzenle">✏️</button>
                                <button class="agent-action-btn duplicate-btn" data-id="${agent.id}" title="Kopyala">📋</button>
                                <button class="agent-action-btn delete" data-id="${agent.id}" title="Sil">🗑️</button>
                            ` : ''}
                        </div>
                        <div class="agent-card-header">
                            <div class="agent-card-icon" style="background: ${agent.color}20; color: ${agent.color}">
                                ${agent.icon}
                            </div>
                            <div>
                                <div class="agent-card-name">${escapeHtml(agent.name)}</div>
                                ${agent.is_default ? '<span class="agent-tool-badge">Varsayılan</span>' : ''}
                            </div>
                        </div>
                        <div class="agent-card-desc">${escapeHtml(agent.description || '')}</div>
                        <div class="agent-card-tools">${toolsHtml}</div>
                    </div>
                `;
            });
            
            // Add model selector and API key section at the bottom
            html += `
                <div class="agent-modal-divider" style="margin: 16px 0; border-top: 1px solid var(--border);"></div>
                <div style="font-size: 0.85rem; color: var(--fg-muted); margin: 8px 0; font-weight: 600;">🧠 AI Modelleri & API Key</div>
                <div class="provider-grid" id="provider-grid-agent-modal" style="grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));"></div>
                
                <div class="api-key-section" style="margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--border);">
                    <div class="api-key-title" style="font-size: 0.85rem; font-weight: 600; color: var(--fg); margin-bottom: 8px;">🔑 API Key Ayarla</div>
                    <div class="api-key-input-group" style="display: flex; gap: 8px;">
                        <select id="api-key-provider-select" class="api-key-input" style="flex: 1; background: var(--input-bg); border: 1px solid var(--input-border); border-radius: var(--radius-md); padding: 8px 12px; color: var(--fg); font-size: 0.85rem;">
                            <option value="">Sağlayıcı seçin...</option>
                        </select>
                        <input type="password" class="api-key-input" id="api-key-input-agent" placeholder="API key girin..." style="flex: 2; background: var(--input-bg); border: 1px solid var(--input-border); border-radius: var(--radius-md); padding: 8px 12px; color: var(--fg); font-size: 0.85rem;">
                        <button class="api-key-save" id="api-key-save-agent" style="background: var(--accent-gradient); border: none; border-radius: var(--radius-md); padding: 8px 16px; color: #fff; font-weight: 600; font-size: 0.85rem; cursor: pointer;">Kaydet</button>
                    </div>
                    <div class="api-key-help" id="api-key-help-agent" style="font-size: 0.75rem; color: var(--fg-dim); margin-top: 6px;">Seçili sağlayıcı için API key girin.</div>
                </div>
            `;
            
            agentGrid.innerHTML = html;
            
            // Add event listeners
            agentGrid.querySelectorAll('.agent-card').forEach(card => {
                card.addEventListener('click', (e) => {
                    if (!e.target.closest('.agent-action-btn')) {
                        selectAgent(card.dataset.id);
                    }
                });
            });
            
            agentGrid.querySelectorAll('.edit-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    openAgentEditor(btn.dataset.id);
                });
            });
            
            agentGrid.querySelectorAll('.duplicate-btn').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    await duplicateAgent(btn.dataset.id);
                });
            });
            
            agentGrid.querySelectorAll('.delete').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    if (confirm('Bu ajanı silmek istediğinize emin misiniz?')) {
                        await deleteAgent(btn.dataset.id);
                    }
                });
            });
        }
        
        // Select agent
        function selectAgent(agentId) {
            currentAgentId = agentId;
            localStorage.setItem('current_agent_id', agentId);
            updateCurrentAgentDisplay();
            renderAgentGrid();
            closeAgentModal();
            // Update header button to show selected agent
            updateHeaderAgentButton(agentId);
        }
        
        // Update header model button to show selected agent
        function updateHeaderAgentButton(agentId) {
            const modelBtnText = document.getElementById('model-btn-text');
            const modelStatusDot = document.getElementById('model-status-dot');
            if (!modelBtnText) return;
            
            const agent = agents.find(a => a.id === agentId);
            if (agent) {
                modelBtnText.textContent = agent.icon + ' ' + agent.name;
                modelStatusDot?.classList.remove('disconnected');
            } else {
                // Default assistant - show model name
                modelBtnText.textContent = 'Model';
            }
        }
        
        // Update current agent display
        function updateCurrentAgentDisplay() {
            const agent = agents.find(a => a.id === currentAgentId);
            if (agent) {
                document.getElementById('current-agent-icon').textContent = agent.icon;
            }
        }
        
        // Open agent editor
        function openAgentEditor(agentId) {
            editingAgentId = agentId;
            agentGridView.style.display = 'none';
            agentEditor.classList.add('active');
            
            if (agentId) {
                // Edit existing agent
                const agent = agents.find(a => a.id === agentId);
                if (agent) {
                    document.getElementById('agent-name-input').value = agent.name;
                    document.getElementById('agent-desc-input').value = agent.description || '';
                    document.getElementById('agent-prompt-input').value = agent.system_prompt || '';
                    selectedIcon = agent.icon;
                    selectedColor = agent.color;
                    selectedTools = agent.tools || [];
                }
            } else {
                // New agent
                document.getElementById('agent-name-input').value = '';
                document.getElementById('agent-desc-input').value = '';
                document.getElementById('agent-prompt-input').value = '';
                selectedIcon = '🤖';
                selectedColor = '#6366f1';
                selectedTools = [];
            }
            
            // Update icon selection
            document.querySelectorAll('.icon-option').forEach(opt => {
                opt.classList.toggle('selected', opt.dataset.icon === selectedIcon);
            });
            
            // Update color selection
            document.querySelectorAll('.color-option').forEach(opt => {
                opt.classList.toggle('selected', opt.dataset.color === selectedColor);
            });
            
            // Render tools
            renderToolsSelector();
        }
        
        // Render tools selector (grouped by category)
        function renderToolsSelector() {
            const container = document.getElementById('agent-tools-selector');
            
            // Group tools
            const groups = {};
            AVAILABLE_TOOLS.forEach(tool => {
                if (!groups[tool.group]) groups[tool.group] = [];
                groups[tool.group].push(tool);
            });
            
            let html = '';
            for (const [groupName, tools] of Object.entries(groups)) {
                html += `<div style="grid-column: 1 / -1; margin-top: 8px; margin-bottom: 4px; font-size: 0.8rem; color: var(--fg-dim); font-weight: 600;">${groupName}</div>`;
                tools.forEach(tool => {
                    html += `
                        <div class="tool-checkbox ${selectedTools.includes(tool.id) ? 'checked' : ''}" data-id="${tool.id}">
                            <span>${tool.icon}</span>
                            <span>${tool.name}</span>
                        </div>
                    `;
                });
            }
            
            container.innerHTML = html;
            
            container.querySelectorAll('.tool-checkbox').forEach(cb => {
                cb.addEventListener('click', () => {
                    const toolId = cb.dataset.id;
                    if (selectedTools.includes(toolId)) {
                        selectedTools = selectedTools.filter(t => t !== toolId);
                        cb.classList.remove('checked');
                    } else {
                        selectedTools.push(toolId);
                        cb.classList.add('checked');
                    }
                });
            });
            
            // Add "Select All" button
            const selectAllBtn = document.createElement('button');
            selectAllBtn.className = 'agent-btn agent-btn-secondary';
            selectAllBtn.style.cssText = 'grid-column: 1 / -1; margin-top: 8px; padding: 6px 12px; font-size: 0.8rem;';
            selectAllBtn.textContent = '✅ Tümünü Seç';
            selectAllBtn.addEventListener('click', () => {
                const allIds = AVAILABLE_TOOLS.map(t => t.id);
                const allSelected = allIds.every(id => selectedTools.includes(id));
                if (allSelected) {
                    selectedTools = [];
                } else {
                    selectedTools = [...allIds];
                }
                renderToolsSelector();
            });
            container.appendChild(selectAllBtn);
        }
        
        // Save agent
        document.getElementById('agent-save-btn').addEventListener('click', async () => {
            const name = document.getElementById('agent-name-input').value.trim();
            const description = document.getElementById('agent-desc-input').value.trim();
            const systemPrompt = document.getElementById('agent-prompt-input').value.trim();
            
            if (!name) {
                alert('Lütfen bir ajan adı girin');
                return;
            }
            
            const data = {
                name,
                description,
                icon: selectedIcon,
                color: selectedColor,
                system_prompt: systemPrompt || 'Sen yardımsever bir asistanısın. Türkçe yanıt ver.',
                tools: selectedTools
            };
            
            try {
                let res;
                if (editingAgentId) {
                    res = await fetch(`${AGENT_API}/${editingAgentId}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(data)
                    });
                } else {
                    res = await fetch(AGENT_API, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(data)
                    });
                }
                
                const result = await res.json();
                if (result.success) {
                    await loadAgents();
                    closeAgentEditor();
                } else {
                    alert('Kaydedilemedi: ' + (result.detail || 'Bilinmeyen hata'));
                }
            } catch (e) {
                alert('Hata: ' + e.message);
            }
        });
        
        // Cancel agent editing
        document.getElementById('agent-cancel-btn').addEventListener('click', closeAgentEditor);
        
        // Close agent editor
        function closeAgentEditor() {
            agentEditor.classList.remove('active');
            agentGridView.style.display = 'block';
            editingAgentId = null;
        }
        
        // Delete agent
        async function deleteAgent(agentId) {
            try {
                const res = await fetch(`${AGENT_API}/${agentId}`, { method: 'DELETE' });
                const data = await res.json();
                if (data.success) {
                    if (currentAgentId === agentId) {
                        currentAgentId = 'main-manager';
                        localStorage.setItem('current_agent_id', 'main-manager');
                    }
                    await loadAgents();
                } else {
                    alert(data.detail || 'Silinemedi');
                }
            } catch (e) {
                alert('Hata: ' + e.message);
            }
        }
        
        // Duplicate agent
        async function duplicateAgent(agentId) {
            try {
                const res = await fetch(`${AGENT_API}/${agentId}/duplicate`, { method: 'POST' });
                const data = await res.json();
                if (data.success) {
                    await loadAgents();
                }
            } catch (e) {
                alert('Hata: ' + e.message);
            }
        }
        
        // Icon picker
        document.querySelectorAll('.icon-option').forEach(opt => {
            opt.addEventListener('click', () => {
                selectedIcon = opt.dataset.icon;
                document.querySelectorAll('.icon-option').forEach(o => o.classList.remove('selected'));
                opt.classList.add('selected');
            });
        });
        
        // Color picker
        document.querySelectorAll('.color-option').forEach(opt => {
            opt.addEventListener('click', () => {
                selectedColor = opt.dataset.color;
                document.querySelectorAll('.color-option').forEach(o => o.classList.remove('selected'));
                opt.classList.add('selected');
            });
        });
        
        // ============================================================
        // MODEL PROVIDER & API KEY IN AGENT MODAL
        // ============================================================
        
        // Load model catalog for agent modal
        async function loadAgentModalCatalog() {
            try {
                const res = await fetch(MODELS_API + '/catalog');
                const data = await res.json();
                if (data.success) {
                    agentModelCatalog = data.catalog;
                    activeProvider = data.active_provider;
                    activeModel = data.active_model;
                    renderAgentModalProviderGrid();
                    populateAgentModalProviderSelect();
                }
            } catch (e) {
                const grid = document.getElementById('provider-grid-agent-modal');
                if (grid) grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:20px;color:var(--fg-dim)">⚠️ Sunucuya bağlanılamadı</div>';
            }
        }
        
        function renderAgentModalProviderGrid() {
            const agentProviderGrid = document.getElementById('provider-grid-agent-modal');
            if (!agentModelCatalog || !agentProviderGrid) return;
            
            agentProviderGrid.innerHTML = agentModelCatalog.map(p => `
                <div class="provider-card ${p.id === activeProvider ? 'active' : ''} ${!p.has_api_key ? 'no-key' : ''}" data-provider="${p.id}" style="cursor: pointer;">
                    <div class="provider-header">
                        <span class="provider-name">${p.name}</span>
                        <span class="provider-badge ${p.free ? 'free' : 'paid'}">${p.free ? 'Ücretsiz' : 'Ücretli'}</span>
                    </div>
                    <div class="provider-status">
                        <span class="provider-status-dot ${p.has_api_key ? 'connected' : 'disconnected'}"></span>
                        ${p.has_api_key ? 'Bağlı' : 'API Key gerekli'}
                        <span style="margin-left:auto;color:var(--fg-dim)">${p.models.length} model</span>
                    </div>
                </div>
            `).join('');
            
            agentProviderGrid.querySelectorAll('.provider-card').forEach(card => {
                card.addEventListener('click', () => {
                    const providerId = card.dataset.provider;
                    selectAgentModalProvider(providerId);
                });
            });
        }
        
        function populateAgentModalProviderSelect() {
            const agentApiKeyProviderSelect = document.getElementById('api-key-provider-select');
            if (!agentModelCatalog || !agentApiKeyProviderSelect) return;
            agentApiKeyProviderSelect.innerHTML = '<option value="">Sağlayıcı seçin...</option>' + 
                agentModelCatalog.map(p => `<option value="${p.id}">${p.name}</option>`).join('');
        }
        
        function selectAgentModalProvider(providerId) {
            selectedProvider = providerId;
            const provider = agentModelCatalog.find(p => p.id === providerId);
            if (!provider) return;
            
            // Update UI
            const agentProviderGrid = document.getElementById('provider-grid-agent-modal');
            if (agentProviderGrid) {
                agentProviderGrid.querySelectorAll('.provider-card').forEach(c => {
                    c.classList.toggle('active', c.dataset.provider === providerId);
                });
            }
            
            // Update API key section
            const urls = {
                'openrouter': 'https://openrouter.ai/keys'
            };
            const agentApiKeyHelp = document.getElementById('api-key-help-agent');
            const agentApiKeyProviderSelect = document.getElementById('api-key-provider-select');
            const agentApiKeyInput = document.getElementById('api-key-input-agent');
            if (agentApiKeyHelp) agentApiKeyHelp.innerHTML = `${provider.name} API key almak için: <a href="${urls[providerId] || '#'}" target="_blank">${urls[providerId] || 'Link'}</a>`;
            if (agentApiKeyProviderSelect) agentApiKeyProviderSelect.value = providerId;
            if (agentApiKeyInput) agentApiKeyInput.placeholder = provider.has_api_key ? 'Key ayarlı (değiştirmek için girin)' : `${provider.name} API key girin...`;
        }
        
        // Save API key from agent modal
        const agentApiKeySave = document.getElementById('api-key-save-agent');
        if (agentApiKeySave) {
            agentApiKeySave.addEventListener('click', async () => {
                const agentApiKeyProviderSelect = document.getElementById('api-key-provider-select');
                const agentApiKeyInput = document.getElementById('api-key-input-agent');
                const providerId = agentApiKeyProviderSelect?.value;
                const key = agentApiKeyInput?.value.trim();
                if (!providerId) { alert('Önce bir sağlayıcı seçin'); return; }
                if (!key) { alert('API key girin'); return; }
                try {
                    const res = await fetch(MODELS_API + '/api-key', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ provider: providerId, api_key: key })
                    });
                    const data = await res.json();
                    if (data.success) {
                        showToast('API key kaydedildi');
                        agentApiKeyInput.value = '';
                        await loadAgentModalCatalog();
                    } else {
                        alert('Kaydedilemedi: ' + (data.detail || 'Hata'));
                    }
                } catch (e) {
                    alert('Hata: ' + e.message);
                }
            });
        }
        
        // Also update when provider select changes - query dynamically
        const agentApiKeyProviderSelectForChange = document.getElementById('api-key-provider-select');
        if (agentApiKeyProviderSelectForChange) {
            agentApiKeyProviderSelectForChange.addEventListener('change', () => {
                selectAgentModalProvider(agentApiKeyProviderSelectForChange.value);
            });
        }
        
        // Close agent modal
        document.getElementById('agent-modal-close').addEventListener('click', closeAgentModal);
        agentModalOverlay.addEventListener('click', (e) => {
            if (e.target === agentModalOverlay) closeAgentModal();
        });
        
        function closeAgentModal() {
            agentModalOverlay.classList.remove('active');
        }

        // Open agent modal (ajan seç veya oluştur)
        async function openAgentModal() {
            // Liste görünümüne dön
            agentGridView.style.display = 'block';
            agentEditor.classList.remove('active');
            agentModalOverlay.classList.add('active');
            // Ajanlar ve model/API paneli açılışta yüklenir
            await loadAgents();
            await loadAgentModalCatalog();
        }
        const agentSelectorBtn = document.getElementById('agent-selector-btn');
        if (agentSelectorBtn) {
            agentSelectorBtn.addEventListener('click', openAgentModal);
        }
        
        // Load agents on startup (also normalizes legacy 'auto'/'team' selections)
        loadAgents();

        // ===== START =====
        initSession();

        // ============================================================
        // PROJECT MANAGEMENT (OpenCode-style)
        // ============================================================
        // PROJECT_API ve FS_API initApp'in başındaki API sabitleriyle birlikte tanımlanır.
        const projectPanel = document.getElementById('project-panel');
        const fileTree = document.getElementById('file-tree');
        const editorOverlay = document.getElementById('editor-overlay');
        const editorContent = document.getElementById('editor-content');
        const editorLineNumbers = document.getElementById('editor-line-numbers');
        const editorFileName = document.getElementById('editor-file-name');
        const editorFilePath = document.getElementById('editor-file-path');
        const editorSave = document.getElementById('editor-save');
        const editorClose = document.getElementById('editor-close');
        const editorStatusDot = document.getElementById('editor-status-dot');
        const editorStatusText = document.getElementById('editor-status-text');
        const editorLineCount = document.getElementById('editor-line-count');
        const editorFileSize = document.getElementById('editor-file-size');

        let currentFilePath = null;
        let originalContent = '';
        let isModified = false;
        let projectOpen = false; // No project open by default
        let currentProjectPath = null; // Açık projenin mutlak yolu (Projeyi Sil için)

        // Toggle project panel
        document.getElementById('project-toggle').addEventListener('click', () => {
            projectPanel.classList.toggle('active');
            if (projectPanel.classList.contains('active')) {
                loadFileTree();
            }
        });

        // Exit project
        document.getElementById('btn-close-project').addEventListener('click', async () => {
            // Call backend to close project
            try {
                await fetch(FS_API + '/close-project', { method: 'POST' });
            } catch (e) {
                console.error('Close project error:', e);
            }
            
            projectOpen = false;
            currentProjectPath = null;
            
            // Close project panel
            projectPanel.classList.remove('active');
            
            // Reset project name
            document.getElementById('project-name').textContent = 'Proje';
            
            // Clear file tree
            fileTree.innerHTML = '<div class="file-tree-empty">📁 Proje seçmek için 📂 butonuna tıklayın</div>';
            
            // Close any open editor
            if (editorOverlay) editorOverlay.classList.remove('active');
            currentFilePath = null;
            
            // Clear current project from localStorage
            localStorage.removeItem('current_project_path');
            
            showToast('📁 Proje kapatıldı');
        });

        // Hide panel (keep project loaded)
        document.getElementById('btn-hide-panel').addEventListener('click', () => {
            projectPanel.classList.remove('active');
            // Close any open editor
            if (editorOverlay) editorOverlay.classList.remove('active');
        });

        // Refresh file tree
        document.getElementById('btn-refresh-tree').addEventListener('click', loadFileTree);

        // Load file tree from API
        async function loadFileTree() {
            if (!projectOpen) {
                fileTree.innerHTML = '<div class="file-tree-empty">📁 Proje açık değil - 📂 ile proje açın</div>';
                return;
            }
            try {
                const res = await fetch(PROJECT_API + '/tree?path=.');
                const data = await res.json();
                if (data.success) {
                    renderFileTree(data.tree);
                }
            } catch (e) {
                fileTree.innerHTML = '<div class="file-tree-empty">⚠️ Sunucuya bağlanılamadı</div>';
            }
        }

        // ============================================================
        // PROJECT FILE OPERATIONS (Yeni dosya/klasör, sil, yeniden adlandır)
        // ============================================================
        function promptRelativePath(message, def) {
            const value = prompt(message, def || '');
            if (value === null) return null;
            const trimmed = value.trim().replace(/\\/g, '/').replace(/^\/+/, '');
            return trimmed || null;
        }

        // Yeni dosya veya klasör oluştur (açık proje köküne göre göreli yol)
        async function createProjectEntry(isDir) {
            if (!projectOpen) { alert('Önce bir proje açın.'); return; }
            const rel = promptRelativePath(
                isDir ? 'Yeni klasör yolu (proje köküne göre):' : 'Yeni dosya yolu (proje köküne göre):',
                isDir ? 'yeni-klasor' : 'yeni-dosya.txt'
            );
            if (!rel) return;
            try {
                const res = await fetch(PROJECT_API + '/create', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path: rel, content: '', is_dir: !!isDir })
                });
                const data = await res.json();
                if (data.success) {
                    await loadFileTree();
                    showToast(isDir ? '📁 Klasör oluşturuldu' : '📄 Dosya oluşturuldu');
                } else {
                    alert('Oluşturulamadı: ' + (data.detail || data.error || 'Bilinmeyen hata'));
                }
            } catch (e) {
                alert('Hata: ' + e.message);
            }
        }
        document.getElementById('btn-new-file').addEventListener('click', () => createProjectEntry(false));
        document.getElementById('btn-new-folder').addEventListener('click', () => createProjectEntry(true));

        // Bir dosya/klasörü yeniden adlandır veya taşı
        async function renameProjectEntry(item) {
            const rel = promptRelativePath('Yeni ad veya yol:', item.path);
            if (!rel || rel === item.path) return;
            try {
                const res = await fetch(PROJECT_API + '/rename', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ old_path: item.path, new_path: rel })
                });
                const data = await res.json();
                if (data.success) {
                    if (currentFilePath === item.path) {
                        currentFilePath = rel;
                        if (editorFilePath) editorFilePath.textContent = rel;
                        if (editorFileName) editorFileName.textContent = rel.split('/').pop();
                    }
                    await loadFileTree();
                    showToast('✏️ Yeniden adlandırıldı');
                } else {
                    alert('Yeniden adlandırılamadı: ' + (data.detail || 'Bilinmeyen hata'));
                }
            } catch (e) {
                alert('Hata: ' + e.message);
            }
        }

        // Bir dosya/klasörü sil
        async function deleteProjectEntry(item) {
            if (!confirm('"' + item.name + '" silinsin mi?')) return;
            try {
                const res = await fetch(PROJECT_API + '/file?path=' + encodeURIComponent(item.path), { method: 'DELETE' });
                const data = await res.json();
                if (data.success) {
                    // Silinen dosya editörde açıksa editörü kapat
                    if (currentFilePath && (currentFilePath === item.path || currentFilePath.startsWith(item.path + '/'))) {
                        if (editorOverlay) editorOverlay.classList.remove('active');
                        currentFilePath = null;
                    }
                    await loadFileTree();
                    showToast('🗑️ Silindi');
                } else {
                    alert('Silinemedi: ' + (data.detail || 'Bilinmeyen hata'));
                }
            } catch (e) {
                alert('Hata: ' + e.message);
            }
        }

        // Dosya ağacı öğeleri için hover aksiyonları (Yeniden adlandır / Sil)
        function buildItemActions(item) {
            const wrap = document.createElement('div');
            wrap.className = 'file-item-actions';
            wrap.innerHTML = `
                <button class="file-action-btn rename-btn" title="Yeniden adlandır">✏️</button>
                <button class="file-action-btn delete-btn" title="Sil">🗑️</button>
            `;
            wrap.querySelector('.rename-btn').addEventListener('click', (e) => { e.stopPropagation(); renameProjectEntry(item); });
            wrap.querySelector('.delete-btn').addEventListener('click', (e) => { e.stopPropagation(); deleteProjectEntry(item); });
            return wrap;
        }

        // Projeyi sil (iki kez onay)
        async function deleteCurrentProject() {
            if (!projectOpen || !currentProjectPath) { alert('Silinecek açık proje yok.'); return; }
            if (!confirm('Bu projeyi silmek istediğinize emin misiniz? Bu işlem geri alınamaz.')) return;
            const name = document.getElementById('project-name').textContent;
            if (!confirm('SON ONAY: "' + name + '" klasörü diskten tamamen silinsin mi?')) return;
            try {
                const res = await fetch(FS_API + '/project?path=' + encodeURIComponent(currentProjectPath), { method: 'DELETE' });
                const data = await res.json();
                if (data.success) {
                    projectOpen = false;
                    currentProjectPath = null;
                    projectPanel.classList.remove('active');
                    document.getElementById('project-name').textContent = 'Proje';
                    fileTree.innerHTML = '<div class="file-tree-empty">📁 Proje seçmek için 📂 butonuna tıklayın</div>';
                    if (editorOverlay) editorOverlay.classList.remove('active');
                    currentFilePath = null;
                    localStorage.removeItem('current_project_path');
                    await loadRecentProjects();
                    showToast('🗑️ Proje silindi');
                } else {
                    alert('Proje silinemedi: ' + (data.detail || 'Bilinmeyen hata'));
                }
            } catch (e) {
                alert('Hata: ' + e.message);
            }
        }
        document.getElementById('btn-delete-project').addEventListener('click', deleteCurrentProject);

        // ============================================================
        // PROJECT BROWSER (OpenCode-style)
        // ============================================================
        const browserOverlay = document.getElementById('project-browser-overlay');
        const browserBody = document.getElementById('browser-body');
        const pathInput = document.getElementById('path-input');
        const browserOpen = document.getElementById('browser-open');
        let selectedProjectPath = null;
        let currentBrowsePath = '';

        // Open project browser
        document.getElementById('btn-open-project').addEventListener('click', async () => {
            browserOverlay.classList.add('active');
            selectedProjectPath = null;
            browserOpen.disabled = true;
            
            // Load current project first
            try {
                const res = await fetch(FS_API + '/current-project');
                const data = await res.json();
                if (data.success) {
                    currentBrowsePath = data.path;
                    pathInput.value = data.path;
                    await browseTo(data.path);
                }
            } catch (e) {
                await loadDrives();
            }
            
            loadRecentProjects();
        });

        // Close browser
        document.getElementById('project-browser-close').addEventListener('click', closeBrowser);
        document.getElementById('browser-cancel').addEventListener('click', closeBrowser);
        browserOverlay.addEventListener('click', (e) => {
            if (e.target === browserOverlay) closeBrowser();
        });

        function closeBrowser() {
            browserOverlay.classList.remove('active');
        }

        // Go to path
        document.getElementById('path-go').addEventListener('click', () => {
            const path = pathInput.value.trim();
            if (path) browseTo(path);
        });

        pathInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                browseTo(pathInput.value.trim());
            }
        });

        // Quick access buttons
        document.getElementById('quick-home').addEventListener('click', async () => {
            const res = await fetch(FS_API + '/home');
            const data = await res.json();
            if (data.success) browseTo(data.path);
        });

        document.getElementById('quick-desktop').addEventListener('click', async () => {
            const res = await fetch(FS_API + '/desktop');
            const data = await res.json();
            if (data.success) browseTo(data.path);
        });

        document.getElementById('quick-documents').addEventListener('click', async () => {
            // path-input boş olabilir (tarayıcı yeni açıldığında); sabit bir
            // varsayım yerine backend'den ev dizinini alıp Belgeler'e gideriz.
            const res = await fetch(FS_API + '/home');
            const data = await res.json();
            if (data.success && data.path) browseTo(data.path + '\\Documents');
        });

        // Yeni klasör oluştur (gezilen dizinde) ve içine gir
        document.getElementById('btn-new-folder-browse').addEventListener('click', async () => {
            if (!currentBrowsePath) { alert('Önce bir klasör seçin.'); return; }
            const name = prompt('Yeni klasör adı:');
            if (!name || !name.trim()) return;
            try {
                const res = await fetch(FS_API + '/create-project', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path: currentBrowsePath, name: name.trim() })
                });
                const data = await res.json();
                if (data.success) {
                    const sep = currentBrowsePath.includes('/') && !currentBrowsePath.includes('\\') ? '/' : '\\';
                    const newPath = data.path || (currentBrowsePath.replace(/[\\/]+$/, '') + sep + name.trim());
                    await browseTo(newPath);
                    await loadRecentProjects();
                    showToast('📁 Klasör oluşturuldu');
                } else {
                    alert('Klasör oluşturulamadı: ' + (data.detail || 'Bilinmeyen hata'));
                }
            } catch (e) {
                alert('Hata: ' + e.message);
            }
        });

        // Browse to directory
        async function browseTo(path) {
            try {
                const res = await fetch(FS_API + '/browse?path=' + encodeURIComponent(path));
                const data = await res.json();
                if (data.success) {
                    currentBrowsePath = data.current_path;
                    pathInput.value = data.current_path;
                    renderBrowserContent(data);
                }
            } catch (e) {
                browserBody.innerHTML = '<div class="browser-empty">⚠️ Hata: ' + e.message + '</div>';
            }
        }

        // Load drives
        async function loadDrives() {
            try {
                const res = await fetch(FS_API + '/drives');
                const data = await res.json();
                if (data.success) {
                    renderDrives(data.drives);
                }
            } catch (e) {
                browserBody.innerHTML = '<div class="browser-empty">⚠️ Sürücüler yüklenemedi</div>';
            }
        }

        function renderDrives(drives) {
            browserBody.innerHTML = drives.map(d => `
                <div class="browser-item folder-item" data-path="${d.path}">
                    <svg class="browser-item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <line x1="4" y1="10" x2="20" y2="10"></line>
                        <line x1="4" y1="14" x2="20" y2="14"></line>
                        <line x1="10" y1="4" x2="8" y2="20"></line>
                        <line x1="16" y1="4" x2="14" y2="20"></line>
                    </svg>
                    <span class="browser-item-name">${d.name}</span>
                </div>
            `).join('');

            browserBody.querySelectorAll('.folder-item').forEach(item => {
                item.addEventListener('click', () => browseTo(item.dataset.path));
            });
        }

        function renderBrowserContent(data) {
            let html = '';

            // Parent directory
            if (data.parent) {
                html += `
                    <div class="browser-item folder-item" data-path="${data.parent}">
                        <svg class="browser-item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="15 18 9 12 15 6"></polyline>
                        </svg>
                        <span class="browser-item-name">.. Üst Klasör</span>
                    </div>
                `;
            }

            // Folders
            data.folders.forEach(f => {
                html += `
                    <div class="browser-item folder-item" data-path="${f.path}" data-name="${f.name}">
                        <svg class="browser-item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
                        </svg>
                        <span class="browser-item-name">${escapeHtml(f.name)}</span>
                        <span class="browser-item-size">Klasör</span>
                    </div>
                `;
            });

            // Files (just for display, not selectable)
            data.files.slice(0, 50).forEach(f => {
                html += `
                    <div class="browser-item file-item">
                        <svg class="browser-item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                            <polyline points="14 2 14 8 20 8"></polyline>
                        </svg>
                        <span class="browser-item-name">${escapeHtml(f.name)}</span>
                        <span class="browser-item-size">${formatFileSize(f.size)}</span>
                    </div>
                `;
            });

            if (!html) html = '<div class="browser-empty">Bu klasör boş</div>';
            browserBody.innerHTML = html;

            // Folder click handlers
            browserBody.querySelectorAll('.folder-item').forEach(item => {
                item.addEventListener('click', (e) => {
                    const path = item.dataset.path;
                    const name = item.dataset.name;
                    
                    if (name) {
                        // This is a subfolder - single click to browse, double-click or Enter to select
                        selectedProjectPath = path;
                        browserOpen.disabled = false;
                        
                        // Visual feedback
                        browserBody.querySelectorAll('.folder-item').forEach(i => i.classList.remove('selected'));
                        item.style.background = 'var(--accent-soft)';
                        item.style.border = '1px solid var(--accent)';
                    } else {
                        // Parent or drive - just navigate
                        browseTo(path);
                    }
                });

                item.addEventListener('dblclick', () => {
                    if (item.dataset.name) {
                        browseTo(item.dataset.path);
                    }
                });
            });
        }

        // Open selected project
        browserOpen.addEventListener('click', async () => {
            if (!selectedProjectPath) return;
            
            try {
                const res = await fetch(FS_API + '/open-project', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path: selectedProjectPath })
                });
                const data = await res.json();
                if (data.success) {
                    projectOpen = true;
                    currentProjectPath = data.path || selectedProjectPath;
                    // Update project name in panel
                    document.getElementById('project-name').textContent = data.name;
                    
                    // Reload file tree
                    await loadFileTree();
                    
                    // Close browser
                    closeBrowser();
                    
                    // Show project panel
                    projectPanel.classList.add('active');
                } else {
                    alert('Proje açılamadı: ' + data.detail);
                }
            } catch (e) {
                alert('Hata: ' + e.message);
            }
        });

        // Load recent projects
        async function loadRecentProjects() {
            try {
                const res = await fetch(FS_API + '/recent-projects');
                const data = await res.json();
                if (data.success && data.projects.length > 0) {
                    const recentDiv = document.getElementById('recent-projects');
                    const recentList = document.getElementById('recent-list');
                    recentDiv.style.display = 'block';
                    
                    recentList.innerHTML = data.projects.map(p => `
                        <div class="recent-item" data-path="${escapeHtml(p.path)}">
                            <svg class="recent-item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
                            </svg>
                            <span class="recent-item-name">${escapeHtml(p.name)}</span>
                            <button class="recent-item-remove" title="Listeden kaldır" aria-label="Listeden kaldır">×</button>
                        </div>
                    `).join('');

                    // Listeden tek bir kaydı kaldır
                    recentList.querySelectorAll('.recent-item-remove').forEach(btn => {
                        btn.addEventListener('click', async (e) => {
                            e.stopPropagation();
                            const item = btn.closest('.recent-item');
                            const path = item?.dataset.path;
                            if (!path) return;
                            try {
                                await fetch(FS_API + '/recent-projects?path=' + encodeURIComponent(path), { method: 'DELETE' });
                                await loadRecentProjects();
                            } catch (err) {
                                console.error('Recent remove error:', err);
                            }
                        });
                    });

                    recentList.querySelectorAll('.recent-item').forEach(item => {
                        item.addEventListener('click', async () => {
                            const path = item.dataset.path;
                            // Open this project directly
                            try {
                                const res = await fetch(FS_API + '/open-project', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ path })
                                });
                                const data = await res.json();
                                if (data.success) {
                                    projectOpen = true;
                                    currentProjectPath = data.path || path;
                                    document.getElementById('project-name').textContent = data.name;
                                    await loadFileTree();
                                    closeBrowser();
                                    projectPanel.classList.add('active');
                                }
                            } catch (e) {
                                alert('Hata: ' + e.message);
                            }
                        });
                    });
                } else {
                    // Kayıt yoksa "Son Açılanlar" bölümünü gizle
                    const recentDiv = document.getElementById('recent-projects');
                    if (recentDiv) recentDiv.style.display = 'none';
                }
            } catch (e) {
                console.error('Recent projects error:', e);
            }
        }

        // Load current project on page load
        async function loadCurrentProject() {
            try {
                const res = await fetch(FS_API + '/current-project');
                const data = await res.json();
                if (data.success && data.is_open) {
                    projectOpen = true;
                    currentProjectPath = data.path || null;
                    document.getElementById('project-name').textContent = data.name;
                    // Proje açıksa dosya ağacını hemen yükle
                    await loadFileTree();
                } else {
                    projectOpen = false;
                    currentProjectPath = null;
                    document.getElementById('project-name').textContent = 'Proje';
                }
            } catch (e) {
                console.error('Current project error:', e);
            }
        }
        loadCurrentProject();

        // Render file tree recursively
        function renderFileTree(items, container = null) {
            if (!container) {
                fileTree.innerHTML = '';
                if (!items || !items.length) {
                    fileTree.innerHTML = '<div class="file-tree-empty">Klasör boş</div>';
                    return;
                }
                container = fileTree;
            }

            items.forEach(item => {
                const el = document.createElement('div');
                el.className = 'file-item' + (item.type === 'dir' ? ' dir-item' : '');
                el.dataset.path = item.path;
                el.dataset.type = item.type;

                if (item.type === 'dir') {
                    el.innerHTML = `
                        <svg class="toggle-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="9 18 15 12 9 6"></polyline>
                        </svg>
                        <svg class="file-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
                        </svg>
                        <span class="file-name">${escapeHtml(item.name)}</span>
                    `;
                    el.addEventListener('click', (e) => {
                        e.stopPropagation();
                        el.classList.toggle('expanded');
                        const childContainer = el.nextElementSibling;
                        if (childContainer && childContainer.classList.contains('file-children')) {
                            childContainer.style.display = childContainer.style.display === 'none' ? 'block' : 'none';
                        } else if (item.children) {
                            const childDiv = document.createElement('div');
                            childDiv.className = 'file-children';
                            renderFileTree(item.children, childDiv);
                            el.after(childDiv);
                        }
                    });
                } else {
                    const icon = getFileIcon(item.name);
                    const size = formatFileSize(item.size || 0);
                    el.innerHTML = `
                        <span style="width:12px"></span>
                        <span class="file-icon">${icon}</span>
                        <span class="file-name">${escapeHtml(item.name)}</span>
                        <span class="file-size">${size}</span>
                    `;
                    el.addEventListener('click', () => openFile(item.path));
                }

                // Hover aksiyonları: Yeniden adlandır / Sil
                el.appendChild(buildItemActions(item));

                container.appendChild(el);
            });
        }

        // Get file icon based on extension
        function getFileIcon(name) {
            const ext = name.split('.').pop().toLowerCase();
            const icons = {
                'py': '🐍', 'js': '📜', 'ts': '📘', 'jsx': '⚛️', 'tsx': '⚛️',
                'html': '🌐', 'css': '🎨', 'json': '📋', 'md': '📝', 'txt': '📄',
                'yml': '⚙️', 'yaml': '⚙️', 'toml': '⚙️', 'cfg': '⚙️', 'ini': '⚙️',
                'sh': '💻', 'bat': '💻', 'cmd': '💻', 'dockerfile': '🐳',
                'sql': '🗄️', 'db': '🗄️', 'env': '🔑', 'lock': '🔒',
                'gitignore': '👁️', 'svg': '🖼️', 'png': '🖼️', 'jpg': '🖼️',
                'zip': '📦', 'tar': '📦', 'gz': '📦'
            };
            return icons[ext] || '📄';
        }

        function formatFileSize(bytes) {
            if (bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
        }

        // Open file in editor
        async function openFile(path) {
            try {
                const res = await fetch(PROJECT_API + '/file?path=' + encodeURIComponent(path));
                const data = await res.json();
                if (data.success) {
                    currentFilePath = path;
                    originalContent = data.content;
                    editorContent.value = data.content;
                    editorFileName.textContent = path.split('/').pop();
                    editorFilePath.textContent = path;
                    editorOverlay.classList.add('active');
                    updateLineNumbers();
                    updateStatus(false, data.size, data.lines);
                    editorSave.disabled = true;
                    isModified = false;

                    // Highlight active file in tree
                    document.querySelectorAll('.file-item').forEach(el => {
                        el.classList.toggle('active', el.dataset.path === path);
                    });
                } else {
                    alert('Dosya açılamadı: ' + data.detail);
                }
            } catch (e) {
                alert('Hata: ' + e.message);
            }
        }

        // Save file
        editorSave.addEventListener('click', async () => {
            if (!currentFilePath) return;
            try {
                const res = await fetch(PROJECT_API + '/file', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path: currentFilePath, content: editorContent.value })
                });
                const data = await res.json();
                if (data.success) {
                    originalContent = editorContent.value;
                    isModified = false;
                    editorSave.disabled = true;
                    updateStatus(false, data.size);
                    loadFileTree(); // Refresh tree for updated sizes
                } else {
                    alert('Kaydedilemedi: ' + data.detail);
                }
            } catch (e) {
                alert('Hata: ' + e.message);
            }
        });

        // Close editor
        editorClose.addEventListener('click', () => {
            if (isModified && !confirm('Kaydedilmemiş değişiklikler var. Kapatmak istiyor musunuz?')) return;
            editorOverlay.classList.remove('active');
            currentFilePath = null;
            document.querySelectorAll('.file-item').forEach(el => el.classList.remove('active'));
        });

        // Close on overlay click
        editorOverlay.addEventListener('click', (e) => {
            if (e.target === editorOverlay) {
                editorClose.click();
            }
        });

        // Editor content changes
        editorContent.addEventListener('input', () => {
            updateLineNumbers();
            const content = editorContent.value;
            isModified = content !== originalContent;
            editorSave.disabled = !isModified;
            updateStatus(isModified, new Blob([content]).size);
        });

        // Tab key support in editor
        editorContent.addEventListener('keydown', (e) => {
            if (e.key === 'Tab') {
                e.preventDefault();
                const start = editorContent.selectionStart;
                const end = editorContent.selectionEnd;
                editorContent.value = editorContent.value.substring(0, start) + '    ' + editorContent.value.substring(end);
                editorContent.selectionStart = editorContent.selectionEnd = start + 4;
                editorContent.dispatchEvent(new Event('input'));
            }
            // Ctrl+S to save
            if (e.ctrlKey && e.key === 's') {
                e.preventDefault();
                editorSave.click();
            }
        });

        // Update line numbers
        function updateLineNumbers() {
            const lines = editorContent.value.split('\n').length;
            let html = '';
            for (let i = 1; i <= lines; i++) {
                html += `<span>${i}</span>`;
            }
            editorLineNumbers.innerHTML = html;
            editorLineCount.textContent = lines + ' satır';
        }

        // Update status bar
        function updateStatus(modified, size, lines) {
            editorStatusDot.classList.toggle('modified', modified);
            editorStatusText.textContent = modified ? 'Değiştirildi' : 'Kaydedildi';
            if (size !== undefined) editorFileSize.textContent = formatFileSize(size);
            if (lines !== undefined) editorLineCount.textContent = lines + ' satır';
        }

        // Sync scroll between line numbers and content
        editorContent.addEventListener('scroll', () => {
            editorLineNumbers.scrollTop = editorContent.scrollTop;
        });

        // Keyboard shortcut: Ctrl+P to toggle project panel
        document.addEventListener('keydown', (e) => {
            if (e.ctrlKey && e.key === 'p') {
                e.preventDefault();
                document.getElementById('project-toggle').click();
            }
        });

        // ============================================================
        // MODEL MANAGEMENT (OpenCode-style)
        // ============================================================
        const modelOverlay = document.getElementById('model-overlay');
        const providerGrid = document.getElementById('provider-grid');
        const providerView = document.getElementById('provider-view');
        const modelView = document.getElementById('model-view');
        const modelItems = document.getElementById('model-items');
        const modelListTitle = document.getElementById('model-list-title');
        const apiKeyInput = document.getElementById('api-key-input');
        const apiKeySave = document.getElementById('api-key-save');
        const apiKeyHelp = document.getElementById('api-key-help');
        const modelBtnText = document.getElementById('model-btn-text');
        const modelStatusDot = document.getElementById('model-status-dot');

        let modelCatalog = null;
        let selectedProvider = null;
        let activeProvider = null;
        let activeModel = null;
        let allAgents = [];
        let agentHierarchy = null;

        // Open model selector
        document.getElementById('model-btn').addEventListener('click', async () => {
            modelOverlay.classList.add('active');
            providerView.style.display = 'block';
            modelView.classList.remove('active');
            await loadModelCatalog();
            await loadAgentsForModal();
        });

        // Close model selector
        document.getElementById('model-modal-close').addEventListener('click', () => {
            modelOverlay.classList.remove('active');
        });

        modelOverlay.addEventListener('click', (e) => {
            if (e.target === modelOverlay) modelOverlay.classList.remove('active');
        });

        // Back to provider view
        document.getElementById('model-list-back').addEventListener('click', () => {
            providerView.style.display = 'block';
            modelView.classList.remove('active');
        });

        // ============================================================
        // AGENTS IN MODEL MODAL
        // ============================================================
        const AGENT_API_URL = `${API_BASE}/api/v1/agents`;
        const HIERARCHY_API_URL = `${API_BASE}/api/v1/agents/hierarchy`;
        const agentGridModal = document.getElementById('agent-grid-modal');
        const agentCountLabel = document.getElementById('agent-count-label');

        // Load agents for modal display
        async function loadAgentsForModal() {
            try {
                const [res, hres] = await Promise.all([
                    fetch(AGENT_API_URL),
                    fetch(HIERARCHY_API_URL).catch(() => null),
                ]);
                const data = await res.json();
                if (data.success) {
                    allAgents = data.agents;
                    if (agentCountLabel) agentCountLabel.textContent = allAgents.length;
                }
                if (hres) {
                    const h = await hres.json().catch(() => null);
                    if (h && h.success && Array.isArray(h.groups) && h.groups.length) {
                        agentHierarchy = h;
                    }
                }
                renderAgentGridModal();
            } catch (e) {
                console.error('Agents load error:', e);
            }
        }

        function agentModalCard(agent, note) {
            if (!agent) return '';
            const isActive = agent.id === currentAgentId;
            const toolsCount = (agent.tools || []).length;
            const color = agent.color || '#64748b';
            return `
                <div class="agent-modal-card ${isActive ? 'active' : ''}" data-id="${agent.id}">
                    <div class="agent-modal-card-icon" style="background: ${color}20; color: ${color}">
                        ${agent.icon || '🤖'}
                    </div>
                    <div class="agent-modal-card-info">
                        <div class="agent-modal-card-name">${escapeHtml(agent.name || agent.id)}</div>
                        <div class="agent-modal-card-desc">${escapeHtml(note || agent.description || '')}</div>
                        <div class="agent-modal-card-tools">${toolsCount} araç</div>
                    </div>
                    ${isActive ? '<span style="color: var(--accent)">✓</span>' : ''}
                </div>
            `;
        }

        function hierarchyHeading(title, subtitle) {
            return `
                <div style="grid-column: 1 / -1; margin: 12px 0 2px; padding-top: 10px; border-top: 1px solid rgba(148,163,184,.18);">
                    <div style="font-size: .78rem; font-weight: 700; letter-spacing: .04em; color: var(--fg-muted); text-transform: uppercase;">${escapeHtml(title)}</div>
                    ${subtitle ? `<div style="font-size: .74rem; color: var(--fg-muted); opacity: .75; margin-top: 2px;">${escapeHtml(subtitle)}</div>` : ''}
                </div>
            `;
        }

        // Render agents in modal — hiyerarşi: Ana Yönetici -> Kodlama Yöneticisi -> 20 uzman
        function renderAgentGridModal() {
            const byId = {};
            allAgents.forEach(a => { byId[a.id] = a; });

            let html = '';
            if (agentHierarchy) {
                const h = agentHierarchy;
                html += hierarchyHeading('Yönetim', 'Ana Yönetici → Kodlama Yöneticisi → uzmanlar');
                html += agentModalCard(byId[h.main_manager.id] || h.main_manager);
                html += hierarchyHeading(
                    `Kodlama Yöneticisi · ${h.total_specialists} uzman`,
                    'Tüm uzmanlar Kodlama Yöneticisi altında çalışır; raporu Ana Yönetici onaylar'
                );
                html += agentModalCard(byId[h.coding_manager.id] || h.coding_manager);

                const used = new Set([h.main_manager.id, h.coding_manager.id]);
                h.groups.forEach(group => {
                    html += hierarchyHeading(group.name, `${group.specialists.length} uzman`);
                    group.specialists.forEach(s => {
                        used.add(s.id);
                        html += agentModalCard(byId[s.id] || s, s.role);
                    });
                });

                const others = allAgents.filter(a => !used.has(a.id));
                if (others.length) {
                    html += hierarchyHeading('Diğer Ajanlar', `${others.length} destek uzmanı`);
                    others.forEach(a => { html += agentModalCard(a); });
                }
            } else {
                allAgents.forEach(a => { html += agentModalCard(a); });
            }
            agentGridModal.innerHTML = html;

            // Click handlers
            agentGridModal.querySelectorAll('.agent-modal-card').forEach(card => {
                card.addEventListener('click', () => {
                    const agentId = card.dataset.id;
                    currentAgentId = agentId;
                    localStorage.setItem('current_agent_id', agentId);
                    updateCurrentAgentDisplay();
                    renderAgentGridModal();
                    modelOverlay.classList.remove('active');
                    
                    // Update header button
                    const modelBtnText = document.getElementById('model-btn-text');
                    const agent = allAgents.find(a => a.id === agentId);
                    if (agent && modelBtnText) {
                        modelBtnText.textContent = agent.icon + ' ' + agent.name;
                    }
                    
                    // Show notification
                    if (agent) {
                        showToast(`${agent.icon} ${agent.name} ajanı seçildi`);
                    }
                });
            });

        }

        // Show toast notification
        function showToast(message) {
            const toast = document.createElement('div');
            toast.style.cssText = 'position:fixed;bottom:100px;left:50%;transform:translateX(-50%);background:var(--bg-surface);border:1px solid var(--accent);color:var(--fg);padding:10px 20px;border-radius:8px;z-index:9999;font-size:0.9rem;box-shadow:0 4px 12px rgba(0,0,0,0.3);';
            toast.textContent = message;
            document.body.appendChild(toast);
            setTimeout(() => toast.remove(), 3000);
        }

        // Load model catalog
        async function loadModelCatalog() {
            try {
                const res = await fetch(MODELS_API + '/catalog');
                const data = await res.json();
                if (data.success) {
                    modelCatalog = data.catalog;
                    activeProvider = data.active_provider;
                    activeModel = data.active_model;
                    renderProviderGrid();
                    updateModelButton();
                }
            } catch (e) {
                providerGrid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:20px;color:var(--fg-dim)">⚠️ Sunucuya bağlanılamadı</div>';
            }
        }

        // Render provider grid
        function renderProviderGrid() {
            if (!modelCatalog) return;
            
            providerGrid.innerHTML = modelCatalog.map(p => `
                <div class="provider-card ${p.id === activeProvider ? 'active' : ''} ${!p.has_api_key ? 'no-key' : ''}" data-provider="${p.id}">
                    <div class="provider-header">
                        <span class="provider-name">${p.name}</span>
                        <span class="provider-badge ${p.free ? 'free' : 'paid'}">${p.free ? 'Ücretsiz' : 'Ücretli'}</span>
                    </div>
                    <div class="provider-status">
                        <span class="provider-status-dot ${p.has_api_key ? 'connected' : 'disconnected'}"></span>
                        ${p.has_api_key ? 'Bağlı' : 'API Key gerekli'}
                        <span style="margin-left:auto;color:var(--fg-dim)">${p.models.length} model</span>
                    </div>
                </div>
            `).join('');

            // Add click handlers
            providerGrid.querySelectorAll('.provider-card').forEach(card => {
                card.addEventListener('click', () => {
                    const providerId = card.dataset.provider;
                    selectProvider(providerId);
                });
            });
        }

        // Select provider
        function selectProvider(providerId) {
            selectedProvider = providerId;
            const provider = modelCatalog.find(p => p.id === providerId);
            if (!provider) return;

            // Update API key section
            const urls = {
                'openrouter': 'https://openrouter.ai/keys'
            };
            apiKeyHelp.innerHTML = `${provider.name} API key almak için: <a href="${urls[providerId] || '#'}" target="_blank">${urls[providerId] || 'Link'}</a>`;
            apiKeyInput.value = '';
            apiKeyInput.placeholder = provider.has_api_key ? 'Key ayarlı (değiştirmek için girin)' : `${provider.name} API key girin...`;

            // Show models
            renderModelList(provider);
            providerView.style.display = 'none';
            modelView.classList.add('active');
            modelListTitle.textContent = `${provider.name} Modelleri`;
        }

        // Render model list
        function renderModelList(provider) {
            modelItems.innerHTML = provider.models.map(m => `
                <div class="model-item ${m.id === activeModel && provider.id === activeProvider ? 'active' : ''}" 
                     data-provider="${provider.id}" data-model="${m.id}" ${!provider.has_api_key ? 'style="opacity:0.5;pointer-events:none"' : ''}>
                    <div class="model-item-info">
                        <div class="model-item-name">
                            ${m.name}
                            ${m.recommended ? '<span class="model-item-recommended">⭐ Önerilen</span>' : ''}
                        </div>
                        <div class="model-item-desc">${m.description}</div>
                    </div>
                    <span class="model-item-context">${m.context}</span>
                    ${m.id === activeModel && provider.id === activeProvider ? '<span class="model-item-check">✓</span>' : ''}
                </div>
            `).join('');

            // Add click handlers
            modelItems.querySelectorAll('.model-item').forEach(item => {
                item.addEventListener('click', async () => {
                    const providerId = item.dataset.provider;
                    const modelId = item.dataset.model;
                    await activateModel(providerId, modelId);
                });
            });
        }

        // Activate model
        async function activateModel(providerId, modelId) {
            try {
                const res = await fetch(MODELS_API + '/activate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ provider: providerId, model: modelId })
                });
                const data = await res.json();
                if (data.success) {
                    activeProvider = providerId;
                    activeModel = modelId;
                    
                    // Update UI
                    const provider = modelCatalog.find(p => p.id === providerId);
                    const model = provider?.models.find(m => m.id === modelId);
                    modelBtnText.textContent = model?.name || modelId;
                    modelStatusDot.classList.remove('disconnected');
                    
                    // Update model list checkmarks
                    renderModelList(provider);
                    
                    // Show confirmation
                    setTimeout(() => {
                        modelOverlay.classList.remove('active');
                    }, 500);
                } else {
                    alert('Model değiştirilemedi: ' + data.detail);
                }
            } catch (e) {
                alert('Hata: ' + e.message);
            }
        }

        // Save API key
        apiKeySave.addEventListener('click', async () => {
            if (!selectedProvider) {
                alert('Önce bir sağlayıcı seçin');
                return;
            }
            const key = apiKeyInput.value.trim();
            try {
                const res = await fetch(MODELS_API + '/api-key', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ provider: selectedProvider, api_key: key })
                });
                const data = await res.json();
                if (data.success) {
                    // Reload catalog
                    await loadModelCatalog();
                    // Re-select provider to update UI
                    selectProvider(selectedProvider);
                    alert('API key kaydedildi!');
                } else {
                    alert('Kaydedilemedi: ' + data.detail);
                }
            } catch (e) {
                alert('Hata: ' + e.message);
            }
        });

        // Update model button on load
        async function updateModelButton() {
            try {
                // Eski localStorage'daki 'assistant', 'auto' veya 'team'
                // secimlerini resmî varsayilan olan Ana Yonetici'ye tasi.
                if (currentAgentId === 'assistant' || currentAgentId === 'auto' || currentAgentId === 'team') {
                    currentAgentId = 'main-manager';
                    localStorage.setItem('current_agent_id', currentAgentId);
                }
                // Check if a specific agent is selected
                if (currentAgentId) {
                    let agent = allAgents.find(a => a.id === currentAgentId) || agents.find(a => a.id === currentAgentId);
                    if (!agent) {
                        try {
                            const ar = await fetch(AGENT_API);
                            const ad = await ar.json();
                            if (ad.success) { agents = ad.agents; agent = agents.find(a => a.id === currentAgentId); }
                        } catch (e) {}
                    }
                    if (agent) {
                        modelBtnText.textContent = agent.icon + ' ' + agent.name;
                        modelStatusDot.classList.remove('disconnected');
                        return;
                    }
                }
                // Default: show model name
                const res = await fetch(MODELS_API + '/active');
                const data = await res.json();
                if (data.success && data.model) {
                    modelBtnText.textContent = data.model_name || data.model;
                    modelStatusDot.classList.remove('disconnected');
                } else {
                    modelBtnText.textContent = 'Model Seç';
                    modelStatusDot.classList.add('disconnected');
                }
            } catch (e) {
                modelBtnText.textContent = 'Model';
            }
        }

        // Load active model on page load
        updateModelButton();
        }
    
