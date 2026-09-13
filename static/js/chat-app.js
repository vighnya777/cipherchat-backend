(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    document.body.classList.add('chat-page');
    document.documentElement.classList.add('chat-page');

    const socket = io({ transports: ['polling', 'websocket'], withCredentials: true, reconnection: true, reconnectionAttempts: 20, reconnectionDelay: 800 });

    const sendBtn = document.getElementById('sendBtn');
    const messageInput = document.getElementById('messageInput');
    const messagesContainer = document.getElementById('messagesContainer');
    const conversationsList = document.getElementById('conversationsList');
    const contactsList = document.getElementById('contactsList');
    const userCount = document.getElementById('userCount');
    const currentChatName = document.getElementById('currentChatName');
    const currentChatStatus = document.getElementById('currentChatStatus');
    const currentChatAvatar = document.getElementById('currentChatAvatar');
    const charCount = document.getElementById('charCount');
    const typingIndicator = document.getElementById('typingIndicator');
    const toggleSidebar = document.getElementById('toggleSidebar');
    const sidebar = document.getElementById('sidebar');
    const chatOverlay = document.getElementById('chatOverlay');
    const chatSettingsBtn = document.getElementById('chatSettingsBtn');
    const chatBody = document.querySelector('.chat-body');

    const currentUser = (window.CIPHERCHAT && window.CIPHERCHAT.userEmail) || '';
    const username = (window.CIPHERCHAT && window.CIPHERCHAT.username) || currentUser;

    let currentRoomName = null;
    let activeUsers = [];
    let conversations = [];
    let typingTimeout = null;
    let isTyping = false;

    function escapeHtml(s) {
      return String(s || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }

    function formatTime(ts) {
      if (!ts) return '';
      try {
        if (String(ts).includes('T') || String(ts).includes('-')) {
          const d = new Date(ts);
          if (!isNaN(d.getTime())) {
            return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
          }
        }
        return String(ts).slice(0, 8);
      } catch (e) {
        return String(ts);
      }
    }

    function scrollToBottom() {
      if (!messagesContainer) return;
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    function showEmptyState(title, body) {
      if (!messagesContainer) return;
      messagesContainer.innerHTML =
        '<div class="empty-state" id="emptyState">' +
        '<div class="empty-state-icon"><i class="bi bi-chat-heart-fill"></i></div>' +
        '<h3>' + escapeHtml(title || 'Start a conversation') + '</h3>' +
        '<p>' + escapeHtml(body || 'Select a chat from the left to begin messaging.') + '</p>' +
        '</div>';
    }

    function clearMessages() {
      if (messagesContainer) messagesContainer.innerHTML = '';
    }

    const generalChatEnabled = !!(window.CIPHERCHAT && window.CIPHERCHAT.generalChatEnabled !== false);

    socket.on('connect', function () {
      if (currentChatStatus) currentChatStatus.textContent = 'online';
      socket.emit('get_active_users');
      if (!currentRoomName && !generalChatEnabled) return;
      var room = currentRoomName || 'general';
      var name = room === 'general' ? 'General Chat' : room;
      currentRoomName = null;
      switchConversation(room, name, room === 'general' ? 'group' : 'private');
    });

    socket.on('disconnect', function () {
      if (currentChatStatus) currentChatStatus.textContent = 'Reconnecting…';
    });

    socket.on('connect_error', function () {
      if (currentChatStatus) currentChatStatus.textContent = 'Connection error';
    });

    socket.on('active_users', function (data) {
      activeUsers = (data && data.users) || [];
      if (userCount) userCount.textContent = String(activeUsers.length);
      renderConversations();
    });

    socket.on('user_joined', function () { socket.emit('get_active_users'); });
    socket.on('user_left', function () { socket.emit('get_active_users'); });

    socket.on('receive_message', function (data) {
      if (!data) return;
      updateConversationPreview(data.room, data.message || '[attachment]', data.timestamp);
      if (data.room === currentRoomName) {
        if (data.message_id && messagesContainer.querySelector('[data-mid="' + data.message_id + '"]')) return;
        displayMessage(data);
        scrollToBottom();
      }
    });

    socket.on('room_history', function (data) {
      if (!data || data.room !== currentRoomName) return;
      clearMessages();
      const msgs = data.messages || [];
      if (!msgs.length) {
        showEmptyState('No messages yet', 'Say hello — your message is end-to-end protected in transit.');
        return;
      }
      msgs.forEach(displayMessage);
      scrollToBottom();
    });

    socket.on('typing', function (data) {
      if (!data || data.room !== currentRoomName || data.email === currentUser) return;
      showTyping(data.email);
    });

    socket.on('stop_typing', function (data) {
      if (!data || data.room !== currentRoomName) return;
      hideTyping();
    });

    socket.on('private_chat_ready', function (data) {
      if (!data || !data.room) return;
      const other = (data.users || []).find(function (u) { return u !== currentUser; }) || 'Private chat';
      let convo = conversations.find(function (c) { return c.id === data.room; });
      if (!convo) {
        convo = { id: data.room, name: other.split('@')[0] || other, type: 'private', unread: currentRoomName === data.room ? 0 : 1, lastMessage: 'Private chat ready', lastTime: '' };
        conversations.unshift(convo);
        renderConversations();
      }
      if (currentRoomName !== data.room) {
        convo.unread = (convo.unread || 0) + (convo.unread ? 0 : 1);
      }
      switchConversation(data.room, other.split('@')[0] || other, 'private');
    });

    socket.on('private_chat_error', function (data) {
      var msg = (data && data.message) || 'Could not open chat.';
      alert(msg);
    });

    socket.on('reaction_update', function (data) {
      if (!data || !data.message_id) return;
      const msgEl = messagesContainer && messagesContainer.querySelector('[data-mid="' + data.message_id + '"]');
      if (!msgEl) return;
      let bar = msgEl.querySelector('.reaction-bar');
      if (!bar) {
        bar = document.createElement('div');
        bar.className = 'reaction-bar';
        const bubble = msgEl.querySelector('.message-bubble');
        if (bubble) bubble.appendChild(bar);
      }
      renderReactionBar(bar, data.reactions || {}, data.message_id, data.room);
    });

    function renderReactionBar(bar, reactions, messageId, room) {
      bar.innerHTML = '';
      const LIKE = '\u2764\ufe0f';
      const count = (reactions[LIKE] || []).length;
      const liked = count > 0 && (reactions[LIKE] || []).includes(currentUser);
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'like-btn' + (liked ? ' liked' : '');
      btn.setAttribute('aria-label', liked ? 'Unlike' : 'Like');
      btn.innerHTML = LIKE + (count > 0 ? ' <span class="like-count">' + count + '</span>' : '');
      btn.addEventListener('click', function () {
        socket.emit('add_reaction', {
          room: room,
          message_id: messageId,
          emoji: LIKE,
          action: liked ? 'remove' : 'add'
        });
      });
      bar.appendChild(btn);
    }

    function loadConversations() {
      // Start with only canonical conversations (general). Contacts should
      // not be seeded into the Chats list — they live under the Contacts
      // / Search UI and must not create chat entries automatically.
      conversations = [{ id: 'general', name: 'General Chat', type: 'group', unread: 0, lastMessage: 'Welcome to CipherChat', lastTime: '' }];
      renderConversations();
    }

    function renderConversations() {
      if (!conversationsList) return;
      conversationsList.innerHTML = '';
      conversations.forEach(function (convo) {
        const el = document.createElement('div');
        el.className = 'conversation-item convo-item' + (convo.id === currentRoomName ? ' active' : '');
        el.dataset.room = convo.id;
        const letter = (convo.name || '?').charAt(0).toUpperCase();
        const isOnline = !!(convo.email && activeUsers.some(function (u) { return u.email === convo.email; }));
        const unreadBadge = convo.unread ? '<span class="badge-count">' + (convo.unread > 99 ? '99+' : convo.unread) + '</span>' : '';
        el.innerHTML =
          '<div class="conversation-avatar convo-avatar' + (isOnline ? ' is-online' : '') + '">' + escapeHtml(letter) + '</div>' +
          '<div class="conversation-info convo-meta">' +
          '<div class="conversation-name convo-top"><span class="convo-name">' + escapeHtml(convo.name) + '</span>' +
          '<span class="convo-time">' + escapeHtml(convo.lastTime || '') + '</span></div>' +
          '<div class="conversation-preview convo-last"><span>' + escapeHtml(convo.lastMessage || '') + '</span>' + unreadBadge + '</div>' +
          '</div>';
        el.addEventListener('click', function () {
          convo.unread = 0;
          if (convo.type === 'contact' && convo.email) {
            openPrivateChat(convo.email, convo.name);
          } else {
            switchConversation(convo.id, convo.name, convo.type);
          }
          renderConversations();
          if (sidebar) sidebar.classList.remove('open');
          if (chatOverlay) chatOverlay.classList.remove('show');
        });
        conversationsList.appendChild(el);
      });
    }

    function updateConversationPreview(roomId, message, timestamp) {
      let convo = conversations.find(function (c) { return c.id === roomId; });
      if (!convo) {
        convo = { id: roomId, name: roomId === 'general' ? 'General Chat' : roomId, type: roomId.startsWith('dm_') ? 'private' : 'group', unread: 0, lastMessage: '', lastTime: '' };
        conversations.unshift(convo);
      }
      convo.lastMessage = (message || '').length > 40 ? message.substring(0, 40) + '…' : (message || '');
      convo.lastTime = formatTime(timestamp);
      if (roomId !== currentRoomName) convo.unread = (convo.unread || 0) + 1;
      renderConversations();
    }

    window.switchConversation = switchConversation;
    function switchConversation(roomId, roomName, roomType) {
      if (!roomId) return;
      if (currentRoomName === roomId) {
        socket.emit('join_room', { room: roomId });
        return;
      }
      if (currentRoomName) socket.emit('leave_room', { room: currentRoomName });
      currentRoomName = roomId;
      socket.emit('join_room', { room: roomId });
      if (currentChatName) currentChatName.textContent = roomName || roomId;
      if (currentChatStatus) currentChatStatus.textContent = roomType === 'group' ? 'Group chat' : (roomType === 'private' ? 'Private chat' : 'Chat');
      if (currentChatAvatar) currentChatAvatar.innerHTML = roomType === 'group' ? '<i class="bi bi-people-fill"></i>' : '<i class="bi bi-person-fill"></i>';
      if (messageInput) messageInput.disabled = false;
      if (sendBtn) sendBtn.disabled = false;
      if (chatSettingsBtn) chatSettingsBtn.style.display = 'block';
      clearMessages();
      showEmptyState('Loading messages…', 'Fetching secure history');
      setTimeout(function () {
        if (currentRoomName === roomId && messagesContainer && messagesContainer.querySelector('.empty-state')) {
          var es = messagesContainer.querySelector('.empty-state h3');
          if (es && es.textContent.indexOf('Loading') !== -1) {
            showEmptyState('No messages yet', socket.connected ? 'Say hello to start the conversation.' : 'Socket disconnected — check server / refresh.');
          }
        }
      }, 2500);
      document.querySelectorAll('.conversation-item').forEach(function (item) {
        item.classList.toggle('active', item.dataset.room === roomId);
      });
    }

    function openPrivateChat(email, name) {
      socket.emit('initiate_private_chat', { target_email: email });
    }

    function displayMessage(data) {
      if (!messagesContainer || !data) return;
      const es = messagesContainer.querySelector('.empty-state');
      if (es) es.remove();

      const own = data.email === currentUser;
      const messageDiv = document.createElement('div');
      messageDiv.className = 'message' + (own ? ' own' : '');
      if (data.message_id) messageDiv.setAttribute('data-mid', data.message_id);

      const bubble = document.createElement('div');
      bubble.className = 'message-bubble';

      if (!own) {
        const name = document.createElement('div');
        name.className = 'message-author';
        name.textContent = (data.email || '').split('@')[0] || 'user';
        bubble.appendChild(name);
      }

      if (data.message) {
        const text = document.createElement('div');
        text.className = 'message-text';
        text.textContent = data.message;
        bubble.appendChild(text);
      }

      if (data.attachment && data.attachment.url) {
        const att = data.attachment;
        if (att.type === 'image') {
          const img = document.createElement('img');
          img.src = att.url;
          img.alt = att.name || 'image';
          img.loading = 'lazy';
          img.style.maxWidth = '260px';
          img.style.borderRadius = '12px';
          img.style.display = 'block';
          img.style.marginTop = '6px';
          bubble.appendChild(img);
        } else {
          const link = document.createElement('a');
          link.href = att.url;
          link.target = '_blank';
          link.rel = 'noopener noreferrer';
          link.textContent = att.name || 'Attachment';
          link.style.display = 'block';
          link.style.marginTop = '8px';
          bubble.appendChild(link);
        }
      }

      const meta = document.createElement('div');
      meta.className = 'message-meta';

      const timeSpan = document.createElement('span');
      timeSpan.textContent = formatTime(data.timestamp);
      meta.appendChild(timeSpan);

      if (own && data.message_id) {
        const tick = document.createElement('span');
        tick.className = 'msg-tick';
        tick.innerHTML = '<i class="bi bi-check2-all"></i>';
        meta.appendChild(tick);
      }
      bubble.appendChild(meta);

      if (data.message_id) {
        const reactionBar = document.createElement('div');
        reactionBar.className = 'reaction-bar';
        const reactions = data.reactions || {};
        renderReactionBar(reactionBar, reactions, data.message_id, data.room || currentRoomName);
        bubble.appendChild(reactionBar);

        bubble.addEventListener('dblclick', function () {
          const LIKE = '\u2764\ufe0f';
          const existing = reactions[LIKE] || [];
          const alreadyLiked = existing.includes(currentUser);
          socket.emit('add_reaction', {
            room: data.room || currentRoomName,
            message_id: data.message_id,
            emoji: LIKE,
            action: alreadyLiked ? 'remove' : 'add'
          });
        });
      }

      messageDiv.appendChild(bubble);
      messagesContainer.appendChild(messageDiv);
    }

    function sendMessage() {
      if (!messageInput || !currentRoomName) return;
      const message = messageInput.value.trim();
      if (!message) return;
      const mid = 'local_' + Date.now() + '_' + Math.random().toString(16).slice(2);
      displayMessage({ message_id: mid, email: currentUser, message: message, room: currentRoomName, timestamp: new Date().toISOString() });
      scrollToBottom();
      updateConversationPreview(currentRoomName, message, new Date().toISOString());
      socket.emit('send_message', { message: message, room: currentRoomName, message_id: mid });
      messageInput.value = '';
      updateCharCount();
      autoResize();
      stopTyping();
    }

    function showTyping(email) {
      if (!typingIndicator) return;
      const span = typingIndicator.querySelector('span');
      if (span) span.textContent = (email.split('@')[0] || email) + ' is typing…';
      typingIndicator.hidden = false;
      typingIndicator.style.display = 'flex';
    }

    function hideTyping() {
      if (!typingIndicator) return;
      typingIndicator.hidden = true;
      typingIndicator.style.display = 'none';
    }

    function startTyping() {
      if (!currentRoomName || isTyping) return;
      isTyping = true;
      socket.emit('typing', { room: currentRoomName });
      clearTimeout(typingTimeout);
      typingTimeout = setTimeout(stopTyping, 1200);
    }

    function stopTyping() {
      if (!isTyping) return;
      isTyping = false;
      socket.emit('stop_typing', { room: currentRoomName });
    }

    function updateCharCount() {
      if (charCount && messageInput) charCount.textContent = String(messageInput.value.length);
    }

    function autoResize() {
      if (!messageInput) return;
      messageInput.style.height = 'auto';
      messageInput.style.height = Math.min(messageInput.scrollHeight, 140) + 'px';
    }

    function setupEventListeners() {
      if (sendBtn) sendBtn.addEventListener('click', sendMessage);
      if (messageInput) {
        messageInput.addEventListener('keydown', function (e) {
          if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
          else startTyping();
        });
        messageInput.addEventListener('input', function () { updateCharCount(); autoResize(); });
      }

      if (toggleSidebar && sidebar) {
        toggleSidebar.addEventListener('click', function () {
          sidebar.classList.toggle('open');
          if (chatOverlay) chatOverlay.classList.toggle('show');
        });
      }
      if (chatOverlay && sidebar) {
        chatOverlay.addEventListener('click', function () {
          sidebar.classList.remove('open');
          chatOverlay.classList.remove('show');
        });
      }
      if (chatSettingsBtn && chatBody) {
        chatSettingsBtn.style.display = '';
        chatSettingsBtn.addEventListener('click', function () { chatBody.classList.toggle('details-open'); });
      }

      document.querySelectorAll('[data-side-tab]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          document.querySelectorAll('[data-side-tab]').forEach(function (b) { b.classList.remove('is-active'); });
          btn.classList.add('is-active');
          const tab = btn.getAttribute('data-side-tab');
          if (tab === 'contacts') {
            if (conversationsList) conversationsList.style.display = 'none';
            if (contactsList) {
              contactsList.style.display = 'block';
              fetch('/get-contacts', { credentials: 'same-origin' })
                .then(function (r) { return r.json(); })
                .then(function (list) {
                  contactsList.innerHTML = (list || []).map(function (u) {
                    return '<div class="contact-item" data-email="' + escapeHtml(u.email) + '" data-username="' + escapeHtml(u.username || u.email) + '">' +
                      '<div class="contact-avatar">' + escapeHtml((u.username || '?').charAt(0).toUpperCase()) + '</div>' +
                      '<div class="convo-meta"><div class="convo-name">' + escapeHtml(u.username || u.email) + '</div>' +
                      '<div class="convo-last">Tap to chat</div></div></div>';
                  }).join('') || '<div class="current-chat-status p-3">No contacts yet.</div>';
                  contactsList.querySelectorAll('.contact-item').forEach(function (item) {
                    item.addEventListener('click', function () { openPrivateChat(item.dataset.email, item.dataset.username); });
                  });
                });
            }
          } else {
            if (conversationsList) conversationsList.style.display = 'block';
            if (contactsList) contactsList.style.display = 'none';
          }
        });
      });

      const findSheet = document.getElementById('findFriendsSheet');
      const findFriendsBtn = document.getElementById('findFriendsBtn');
      const closeFindFriendsBtn = document.getElementById('closeFindFriendsBtn');
      const pickContactsBtn = document.getElementById('pickContactsBtn');
      const unsupportedEl = document.getElementById('contactPickerUnsupported');
      const matchedBox = document.getElementById('matchedContacts');
      const manualSearch = document.getElementById('manualContactSearch');

      function openFindFriends() {
        if (!findSheet) return;
        findSheet.classList.add('open');
        const supported = !!(navigator.contacts && navigator.contacts.select);
        if (unsupportedEl) unsupportedEl.style.display = supported ? 'none' : 'block';
        if (pickContactsBtn) pickContactsBtn.style.display = supported ? 'inline-flex' : 'none';
      }
      function closeFindFriends() { if (findSheet) findSheet.classList.remove('open'); }
      if (findFriendsBtn) findFriendsBtn.addEventListener('click', openFindFriends);
      if (closeFindFriendsBtn) closeFindFriendsBtn.addEventListener('click', closeFindFriends);

      async function matchContactsPayload(payload) {
        if (!matchedBox) return;
        matchedBox.innerHTML = '<div class="current-chat-status">Matching…</div>';
        try {
          const res = await fetch('/match-contacts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin', body: JSON.stringify(payload) });
          const data = await res.json();
          const list = data.matched || [];
          if (!list.length) { matchedBox.innerHTML = '<div class="current-chat-status">No CipherChat users found.</div>'; return; }
          matchedBox.innerHTML = list.map(function (u) {
            return '<div class="contact-result"><div class="contact-avatar">' + escapeHtml((u.username || '?').charAt(0).toUpperCase()) + '</div><div><div class="convo-name">' +
              escapeHtml(u.username) + '</div><div class="convo-last">On CipherChat Pro</div></div>' +
              '<div class="actions"><button type="button" class="btn btn-sm btn-primary start-chat-btn" data-email="' + escapeHtml(u.email) + '" data-username="' + escapeHtml(u.username) + '">Chat</button></div></div>';
          }).join('');
          matchedBox.querySelectorAll('.start-chat-btn').forEach(function (btn) {
            btn.addEventListener('click', function () { openPrivateChat(btn.dataset.email, btn.dataset.username); closeFindFriends(); });
          });
        } catch (e) {
          matchedBox.innerHTML = '<div class="current-chat-status">Unable to match contacts.</div>';
        }
      }

      if (pickContactsBtn) {
        pickContactsBtn.addEventListener('click', async function () {
          if (!(navigator.contacts && navigator.contacts.select)) return;
          try {
            const selected = await navigator.contacts.select(['name', 'email', 'tel'], { multiple: true });
            const contacts = (selected || []).map(function (c) { return { name: (c.name && c.name[0]) || '', email: (c.email && c.email[0]) || '', tel: (c.tel && c.tel[0]) || '' }; });
            await matchContactsPayload({ contacts: contacts });
          } catch (e) {
            matchedBox.innerHTML = '<div class="current-chat-status">Contact access cancelled or denied.</div>';
          }
        });
      }

      let searchTimer = null;
      if (manualSearch) {
        manualSearch.addEventListener('input', function () {
          clearTimeout(searchTimer);
          const q = manualSearch.value.trim();
          searchTimer = setTimeout(function () { if (q.length >= 2) matchContactsPayload({ query: q, contacts: [] }); }, 300);
        });
      }

      const newMessageBtn = document.getElementById('newMessageBtn');
      const newChatMenu = document.getElementById('newChatMenu');
      if (newMessageBtn && newChatMenu) {
        newMessageBtn.addEventListener('click', function (e) {
          e.stopPropagation();
          const willOpen = !newChatMenu.classList.contains('open');
          newChatMenu.classList.toggle('open', willOpen);
          newChatMenu.setAttribute('aria-hidden', willOpen ? 'false' : 'true');
        });
        document.addEventListener('click', function () {
          newChatMenu.classList.remove('open');
          newChatMenu.setAttribute('aria-hidden', 'true');
        });
        newChatMenu.querySelectorAll('[data-menu-action]').forEach(function (btn) {
          btn.addEventListener('click', function (e) {
            e.stopPropagation();
            newChatMenu.classList.remove('open');
            newChatMenu.setAttribute('aria-hidden', 'true');
            const action = btn.getAttribute('data-menu-action');
            if (action === 'find-friends' && findFriendsBtn) findFriendsBtn.click();
            else if (action === 'new-group') document.dispatchEvent(new CustomEvent('cc:open-new-group'));
            else if (action === 'general') switchConversation('general', 'General Chat', 'group');
          });
        });
      }

      const attachBtn = document.getElementById('attachBtn');
      const fileInput = document.getElementById('fileInput');
      if (attachBtn && fileInput) attachBtn.addEventListener('click', function () { fileInput.click(); });
    }

    setupEventListeners();
    loadConversations();
    if (messageInput) { messageInput.disabled = false; messageInput.removeAttribute('disabled'); messageInput.style.pointerEvents = 'auto'; }
    if (sendBtn) { sendBtn.disabled = false; sendBtn.removeAttribute('disabled'); }
    if (generalChatEnabled) {
      switchConversation('general', 'General Chat', 'group');
    } else {
      showEmptyState('Pick a chat', 'Choose a contact or group from the left to start messaging.');
    }

    window.CipherChatApp = {
      socket: socket,
      escapeHtml: escapeHtml,
      formatTime: formatTime,
      getCurrentUser: function () { return currentUser; },
      getCurrentRoom: function () { return currentRoomName; },
      switchConversation: switchConversation,
      addConversation: function (convo) {
        if (!conversations.find(function (c) { return c.id === convo.id; })) {
          conversations.unshift(convo);
        }
        renderConversations();
      },
      removeConversation: function (id) {
        conversations = conversations.filter(function (c) { return c.id !== id; });
        renderConversations();
      },
      getSidebarEls: function () { return { sidebar: sidebar, chatOverlay: chatOverlay, chatBody: chatBody }; }
    };
    document.dispatchEvent(new CustomEvent('cc:app-ready'));
  });
})();
