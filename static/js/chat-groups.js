(function () {
  'use strict';

  document.addEventListener('cc:app-ready', init);

  function init() {
    const app = window.CipherChatApp;
    if (!app) return;
    const socket = app.socket;
    const escapeHtml = app.escapeHtml;
    const currentUser = app.getCurrentUser();

    const groupsList = document.getElementById('groupsList');
    const conversationsList = document.getElementById('conversationsList');
    const contactsList = document.getElementById('contactsList');

    const newGroupSheet = document.getElementById('newGroupSheet');
    const newGroupName = document.getElementById('newGroupName');
    const newGroupMembers = document.getElementById('newGroupMembers');
    const createGroupBtn = document.getElementById('createGroupBtn');
    const closeNewGroupBtn = document.getElementById('closeNewGroupBtn');

    const addMemberSheet = document.getElementById('addMemberSheet');
    const addMemberList = document.getElementById('addMemberList');
    const closeAddMemberBtn = document.getElementById('closeAddMemberBtn');

    const groupMembersSection = document.getElementById('groupMembersSection');
    const groupMembersList = document.getElementById('groupMembersList');
    const groupActionsSection = document.getElementById('groupActionsSection');
    const groupAddMemberBtn = document.getElementById('groupAddMemberBtn');
    const groupRenameBtn = document.getElementById('groupRenameBtn');
    const groupLeaveBtn = document.getElementById('groupLeaveBtn');
    const detailsAvatar = document.getElementById('detailsAvatar');
    const detailsName = document.getElementById('detailsName');
    const detailsStatus = document.getElementById('detailsStatus');

    let myGroups = [];
    let activeGroupId = null;

    function api(url, opts) {
      opts = opts || {};
      opts.credentials = 'same-origin';
      opts.headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
      return fetch(url, opts).then(function (r) {
        return r.json().then(function (data) { return { ok: r.ok, data: data }; });
      });
    }

    function nameFor(email) { return (email || '').split('@')[0] || email; }

    function loadGroups() {
      api('/groups').then(function (res) {
        myGroups = res.ok ? (res.data || []) : [];
        renderGroupsTab();
        renderGroupsIntoChats();
      });
    }

    function renderGroupsTab() {
      if (!groupsList) return;
      if (!myGroups.length) {
        groupsList.innerHTML = '<div class="current-chat-status p-3">No groups yet. Use "New message" → "New group".</div>';
        return;
      }
      groupsList.innerHTML = myGroups.map(function (g) {
        return '<div class="contact-item" data-group="' + g.id + '">' +
          '<div class="contact-avatar"><i class="bi bi-people-fill"></i></div>' +
          '<div class="convo-meta"><div class="convo-name">' + escapeHtml(g.name) + '</div>' +
          '<div class="convo-last">' + g.member_count + ' members' + (g.is_admin ? ' · admin' : '') + '</div></div></div>';
      }).join('');
      groupsList.querySelectorAll('[data-group]').forEach(function (item) {
        item.addEventListener('click', function () {
          const g = myGroups.find(function (x) { return x.id === item.dataset.group; });
          if (g) openGroup(g);
        });
      });
    }

    function renderGroupsIntoChats() {
      myGroups.forEach(function (g) {
        app.addConversation({
          id: g.id,
          name: g.name,
          type: 'group',
          unread: 0,
          lastMessage: g.member_count + ' members',
          lastTime: ''
        });
      });
    }

    function openGroup(g) {
      activeGroupId = g.id;
      app.switchConversation(g.id, g.name, 'group');
      renderGroupDetails(g);
      if (contactsList) contactsList.style.display = 'none';
      if (groupsList) groupsList.style.display = 'none';
      if (conversationsList) conversationsList.style.display = 'block';
      document.querySelectorAll('[data-side-tab]').forEach(function (b) { b.classList.remove('is-active'); });
      const chatsTabBtn = document.querySelector('[data-side-tab="chats"]');
      if (chatsTabBtn) chatsTabBtn.classList.add('is-active');
      const sidebarEls = app.getSidebarEls();
      if (sidebarEls.sidebar) sidebarEls.sidebar.classList.remove('open');
      if (sidebarEls.chatOverlay) sidebarEls.chatOverlay.classList.remove('show');
    }

    function renderGroupDetails(g) {
      if (detailsAvatar) detailsAvatar.textContent = (g.name || '?').charAt(0).toUpperCase();
      if (detailsName) detailsName.textContent = g.name;
      if (detailsStatus) detailsStatus.textContent = g.member_count + ' members';
      if (groupMembersSection) groupMembersSection.style.display = 'block';
      if (groupActionsSection) groupActionsSection.style.display = 'block';
      if (groupAddMemberBtn) groupAddMemberBtn.style.display = g.is_admin ? 'flex' : 'none';
      if (!groupMembersList) return;
      groupMembersList.innerHTML = g.members.map(function (email) {
        const isAdmin = g.admins.indexOf(email) !== -1;
        const isOwner = email === g.owner;
        const isSelf = email === currentUser;
        let actions = '';
        if (g.is_admin && !isSelf) {
          actions += '<button type="button" class="header-btn" data-act="toggle-admin" data-email="' + escapeHtml(email) + '" data-make="' + (isAdmin ? '0' : '1') + '">' +
            (isAdmin ? 'Remove admin' : 'Make admin') + '</button>';
          if (!isOwner) {
            actions += '<button type="button" class="header-btn danger" data-act="remove" data-email="' + escapeHtml(email) + '">Remove</button>';
          }
        }
        return '<div class="member-row">' +
          '<div class="contact-avatar" style="width:36px;height:36px;font-size:14px">' + escapeHtml(nameFor(email).charAt(0).toUpperCase()) + '</div>' +
          '<div class="member-info"><div class="convo-name">' + escapeHtml(nameFor(email)) + (isSelf ? ' (you)' : '') + '</div>' +
          '<div class="convo-last">' + (isOwner ? 'Owner' : (isAdmin ? 'Admin' : 'Member')) + '</div></div>' +
          '<div class="member-actions">' + actions + '</div></div>';
      }).join('');

      groupMembersList.querySelectorAll('[data-act="toggle-admin"]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          api('/groups/' + g.id + '/admins', {
            method: 'POST',
            body: JSON.stringify({ email: btn.dataset.email, make_admin: btn.dataset.make === '1' })
          }).then(function (res) {
            if (res.ok) refreshGroup(g.id);
          });
        });
      });
      groupMembersList.querySelectorAll('[data-act="remove"]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          if (!confirm('Remove ' + nameFor(btn.dataset.email) + ' from this group?')) return;
          api('/groups/' + g.id + '/members/' + encodeURIComponent(btn.dataset.email), { method: 'DELETE' }).then(function (res) {
            if (res.ok) refreshGroup(g.id);
          });
        });
      });
    }

    function refreshGroup(groupId) {
      api('/groups/' + groupId).then(function (res) {
        if (!res.ok) return;
        const idx = myGroups.findIndex(function (g) { return g.id === groupId; });
        if (idx !== -1) myGroups[idx] = res.data; else myGroups.push(res.data);
        renderGroupsTab();
        if (activeGroupId === groupId) renderGroupDetails(res.data);
      });
    }

    if (groupRenameBtn) {
      groupRenameBtn.addEventListener('click', function () {
        if (!activeGroupId) return;
        const g = myGroups.find(function (x) { return x.id === activeGroupId; });
        const newName = prompt('New group name', g ? g.name : '');
        if (!newName || !newName.trim()) return;
        api('/groups/' + activeGroupId, { method: 'PATCH', body: JSON.stringify({ name: newName.trim() }) })
          .then(function (res) { if (res.ok) refreshGroup(activeGroupId); });
      });
    }

    if (groupLeaveBtn) {
      groupLeaveBtn.addEventListener('click', function () {
        if (!activeGroupId) return;
        if (!confirm('Leave this group?')) return;
        api('/groups/' + activeGroupId + '/leave', { method: 'POST' }).then(function (res) {
          if (res.ok) {
            app.removeConversation(activeGroupId);
            myGroups = myGroups.filter(function (g) { return g.id !== activeGroupId; });
            activeGroupId = null;
            renderGroupsTab();
            if (groupMembersSection) groupMembersSection.style.display = 'none';
            if (groupActionsSection) groupActionsSection.style.display = 'none';
          }
        });
      });
    }

    function closeSheet(el) { if (el) { el.classList.remove('open'); el.setAttribute('aria-hidden', 'true'); } }
    function openSheet(el) { if (el) { el.classList.add('open'); el.setAttribute('aria-hidden', 'false'); } }

    document.addEventListener('cc:open-new-group', function () {
      openSheet(newGroupSheet);
      if (newGroupName) newGroupName.value = '';
      if (newGroupMembers) newGroupMembers.innerHTML = '<div class="current-chat-status">Loading contacts…</div>';
      api('/get-contacts').then(function (res) {
        const list = res.ok ? (res.data || []) : [];
        if (!newGroupMembers) return;
        if (!list.length) {
          newGroupMembers.innerHTML = '<div class="current-chat-status">No contacts yet — add friends first.</div>';
          return;
        }
        newGroupMembers.innerHTML = list.map(function (u) {
          return '<label class="member-pick">' +
            '<input type="checkbox" value="' + escapeHtml(u.email) + '">' +
            '<div class="contact-avatar" style="width:34px;height:34px;font-size:13px">' + escapeHtml((u.username || '?').charAt(0).toUpperCase()) + '</div>' +
            '<span>' + escapeHtml(u.username || u.email) + '</span></label>';
        }).join('');
      });
    });

    if (closeNewGroupBtn) closeNewGroupBtn.addEventListener('click', function () { closeSheet(newGroupSheet); });
    if (newGroupSheet) newGroupSheet.addEventListener('click', function (e) { if (e.target === newGroupSheet) closeSheet(newGroupSheet); });

    if (createGroupBtn) {
      createGroupBtn.addEventListener('click', function () {
        const name = (newGroupName && newGroupName.value || '').trim();
        if (!name) { if (newGroupName) newGroupName.focus(); return; }
        const members = Array.prototype.slice.call(newGroupMembers.querySelectorAll('input:checked')).map(function (i) { return i.value; });
        createGroupBtn.disabled = true;
        api('/groups', { method: 'POST', body: JSON.stringify({ name: name, members: members }) })
          .then(function (res) {
            createGroupBtn.disabled = false;
            if (!res.ok) { alert(res.data.error || 'Could not create group.'); return; }
            closeSheet(newGroupSheet);
            myGroups.unshift(res.data.group);
            renderGroupsTab();
            openGroup(res.data.group);
          });
      });
    }

    if (groupAddMemberBtn) {
      groupAddMemberBtn.addEventListener('click', function () {
        if (!activeGroupId) return;
        openSheet(addMemberSheet);
        if (addMemberList) addMemberList.innerHTML = '<div class="current-chat-status">Loading contacts…</div>';
        const g = myGroups.find(function (x) { return x.id === activeGroupId; });
        api('/get-contacts').then(function (res) {
          const list = res.ok ? (res.data || []) : [];
          const already = new Set((g && g.members) || []);
          const remaining = list.filter(function (u) { return !already.has(u.email); });
          if (!addMemberList) return;
          if (!remaining.length) {
            addMemberList.innerHTML = '<div class="current-chat-status">All your contacts are already in this group.</div>';
            return;
          }
          addMemberList.innerHTML = remaining.map(function (u) {
            return '<div class="contact-result"><div class="contact-avatar">' + escapeHtml((u.username || '?').charAt(0).toUpperCase()) + '</div><div><div class="convo-name">' +
              escapeHtml(u.username || u.email) + '</div></div><div class="actions"><button type="button" class="btn-new" style="height:34px;padding:0 12px" data-email="' + escapeHtml(u.email) + '">Add</button></div></div>';
          }).join('');
          addMemberList.querySelectorAll('[data-email]').forEach(function (btn) {
            btn.addEventListener('click', function () {
              api('/groups/' + activeGroupId + '/members', { method: 'POST', body: JSON.stringify({ email: btn.dataset.email }) })
                .then(function (r) {
                  if (r.ok) { refreshGroup(activeGroupId); btn.closest('.contact-result').remove(); }
                });
            });
          });
        });
      });
    }
    if (closeAddMemberBtn) closeAddMemberBtn.addEventListener('click', function () { closeSheet(addMemberSheet); });
    if (addMemberSheet) addMemberSheet.addEventListener('click', function (e) { if (e.target === addMemberSheet) closeSheet(addMemberSheet); });

    document.querySelectorAll('[data-side-tab="groups"]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (conversationsList) conversationsList.style.display = 'none';
        if (contactsList) contactsList.style.display = 'none';
        if (groupsList) groupsList.style.display = 'block';
        loadGroups();
      });
    });
    document.querySelectorAll('[data-side-tab="chats"], [data-side-tab="contacts"]').forEach(function (btn) {
      btn.addEventListener('click', function () { if (groupsList) groupsList.style.display = 'none'; });
    });

    if (socket) {
      socket.on('group_created', function (data) {
        if (!data || !data.group) return;
        const members = data.group.members || [];
        if (members.indexOf(currentUser) === -1) return;
        if (!myGroups.find(function (g) { return g.id === data.group.id; })) {
          myGroups.unshift(data.group);
          renderGroupsTab();
          app.addConversation({ id: data.group.id, name: data.group.name, type: 'group', unread: 0, lastMessage: 'Added you to this group', lastTime: '' });
        }
      });
      socket.on('group_updated', function (data) {
        if (!data || !data.group) return;
        refreshGroup(data.group.id);
      });
      socket.on('group_member_removed', function (data) {
        if (!data || !data.group) return;
        if (data.removed_email === currentUser) {
          myGroups = myGroups.filter(function (g) { return g.id !== data.group.id; });
          app.removeConversation(data.group.id);
          renderGroupsTab();
          if (activeGroupId === data.group.id) {
            activeGroupId = null;
            if (groupMembersSection) groupMembersSection.style.display = 'none';
            if (groupActionsSection) groupActionsSection.style.display = 'none';
          }
        } else {
          refreshGroup(data.group.id);
        }
      });
    }

    loadGroups();
  }
})();
