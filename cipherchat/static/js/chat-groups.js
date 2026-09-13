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
    const newGroupDescription = document.getElementById('newGroupDescription');
    const newGroupMembers = document.getElementById('newGroupMembers');
    const newGroupMemberSearch = document.getElementById('newGroupMemberSearch');
    const newGroupSelectedCount = document.getElementById('newGroupSelectedCount');
    const newGroupMembersCanAdd = document.getElementById('newGroupMembersCanAdd');
    const newGroupPhotoBtn = document.getElementById('newGroupPhotoBtn');
    const newGroupPhotoInput = document.getElementById('newGroupPhotoInput');
    const newGroupPhotoPreview = document.getElementById('newGroupPhotoPreview');
    const newGroupPhotoIcon = document.getElementById('newGroupPhotoIcon');
    const newGroupPhotoStatus = document.getElementById('newGroupPhotoStatus');
    const newGroupReview = document.getElementById('newGroupReview');
    const newGroupBackBtn = document.getElementById('newGroupBackBtn');
    const newGroupNextBtn = document.getElementById('newGroupNextBtn');
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

    // ---------------------------------------------------------------------
    // New group wizard: 1 Members -> 2 Info -> 3 Settings -> 4 Review
    // ---------------------------------------------------------------------
    const wizardPanels = newGroupSheet ? Array.prototype.slice.call(newGroupSheet.querySelectorAll('[data-wizard-panel]')) : [];
    const wizardDots = newGroupSheet ? Array.prototype.slice.call(newGroupSheet.querySelectorAll('[data-step-dot]')) : [];
    let wizardStep = 1;
    let wizardCandidates = []; // { email, username, display_name, online }
    const wizardSelected = new Map(); // email -> candidate
    let wizardAvatarUrl = null;
    let wizardUploadingPhoto = false;
    let wizardSubmitting = false;
    let wizardSearchDebounce = null;

    function wizardGoTo(step) {
      wizardStep = step;
      wizardPanels.forEach(function (p) { p.classList.toggle('is-active', Number(p.dataset.wizardPanel) === step); });
      wizardDots.forEach(function (d) {
        const n = Number(d.dataset.stepDot);
        d.classList.toggle('is-active', n === step);
        d.classList.toggle('is-done', n < step);
      });
      if (newGroupBackBtn) newGroupBackBtn.style.display = step > 1 ? 'inline-flex' : 'none';
      if (newGroupNextBtn) newGroupNextBtn.style.display = step < 4 ? 'inline-block' : 'none';
      if (createGroupBtn) createGroupBtn.style.display = step === 4 ? 'inline-block' : 'none';
      if (step === 4) renderReview();
    }

    function wizardReset() {
      wizardStep = 1;
      wizardCandidates = [];
      wizardSelected.clear();
      wizardAvatarUrl = null;
      wizardUploadingPhoto = false;
      wizardSubmitting = false;
      if (newGroupName) newGroupName.value = '';
      if (newGroupDescription) newGroupDescription.value = '';
      if (newGroupMemberSearch) newGroupMemberSearch.value = '';
      if (newGroupMembersCanAdd) newGroupMembersCanAdd.checked = false;
      if (newGroupPhotoPreview) { newGroupPhotoPreview.style.display = 'none'; newGroupPhotoPreview.src = ''; }
      if (newGroupPhotoIcon) newGroupPhotoIcon.style.display = 'inline-block';
      if (newGroupPhotoStatus) newGroupPhotoStatus.textContent = 'Optional group photo';
      if (createGroupBtn) { createGroupBtn.disabled = false; createGroupBtn.textContent = 'Create group'; }
      wizardGoTo(1);
      loadDefaultCandidates();
    }

    function renderMemberList(list) {
      if (!newGroupMembers) return;
      if (!list.length) {
        newGroupMembers.innerHTML = '<div class="current-chat-status p-3">No users found.</div>';
        return;
      }
      newGroupMembers.innerHTML = list.map(function (u) {
        const checked = wizardSelected.has(u.email) ? ' checked' : '';
        const statusText = u.online ? 'Online' : 'Offline';
        return '<label class="member-pick">' +
          '<input type="checkbox" value="' + escapeHtml(u.email) + '"' + checked + '>' +
          '<div class="contact-avatar' + (u.online ? ' is-online' : '') + '" style="width:34px;height:34px;font-size:13px">' +
          escapeHtml((u.display_name || u.username || '?').charAt(0).toUpperCase()) + '</div>' +
          '<span>' + escapeHtml(u.display_name || u.username || u.email) + '<br><small style="color:var(--muted);font-weight:500">' +
          statusText + '</small></span></label>';
      }).join('');
      newGroupMembers.querySelectorAll('input[type="checkbox"]').forEach(function (box) {
        box.addEventListener('change', function () {
          const email = box.value;
          const candidate = wizardCandidates.find(function (c) { return c.email === email; }) ||
            { email: email, username: email, display_name: email };
          // Duplicate-prevention lives in this single source of truth (a Map
          // keyed by email) rather than trusting checkbox state alone.
          if (box.checked) wizardSelected.set(email, candidate);
          else wizardSelected.delete(email);
          updateSelectedCount();
        });
      });
    }

    function updateSelectedCount() {
      if (newGroupSelectedCount) {
        const n = wizardSelected.size;
        newGroupSelectedCount.textContent = n + ' selected';
      }
    }

    function loadDefaultCandidates() {
      if (newGroupMembers) newGroupMembers.innerHTML = '<div class="current-chat-status">Loading contacts…</div>';
      api('/get-contacts').then(function (res) {
        const list = res.ok && res.data && Array.isArray(res.data.contacts) ? res.data.contacts : [];
        wizardCandidates = list.map(function (u) {
          return {
            email: u.email,
            username: u.username,
            display_name: u.display_name || u.username,
            online: !!u.online,
          };
        });
        renderMemberList(wizardCandidates);
      });
    }

    if (newGroupMemberSearch) {
      newGroupMemberSearch.addEventListener('input', function () {
        const q = newGroupMemberSearch.value.trim();
        clearTimeout(wizardSearchDebounce);
        if (!q) { loadDefaultCandidates(); return; }
        wizardSearchDebounce = setTimeout(function () {
          fetch('/search-users?q=' + encodeURIComponent(q), { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (payload) {
              wizardCandidates = Array.isArray(payload) ? payload : (payload && payload.results) || [];
              renderMemberList(wizardCandidates);
            })
            .catch(function () {
              if (newGroupMembers) newGroupMembers.innerHTML = '<div class="current-chat-status p-3">Search failed.</div>';
            });
        }, 300);
      });
    }

    if (newGroupPhotoBtn && newGroupPhotoInput) {
      newGroupPhotoBtn.addEventListener('click', function () { newGroupPhotoInput.click(); });
      newGroupPhotoInput.addEventListener('change', function () {
        const file = newGroupPhotoInput.files && newGroupPhotoInput.files[0];
        if (!file) return;
        wizardUploadingPhoto = true;
        if (newGroupPhotoStatus) newGroupPhotoStatus.textContent = 'Uploading…';
        const fd = new FormData();
        fd.append('file', file);
        fetch('/upload', { method: 'POST', credentials: 'same-origin', body: fd })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            wizardUploadingPhoto = false;
            if (!data || !data.success) {
              if (newGroupPhotoStatus) newGroupPhotoStatus.textContent = data && data.error ? data.error : 'Upload failed.';
              return;
            }
            wizardAvatarUrl = data.url;
            if (newGroupPhotoPreview) { newGroupPhotoPreview.src = data.url; newGroupPhotoPreview.style.display = 'block'; }
            if (newGroupPhotoIcon) newGroupPhotoIcon.style.display = 'none';
            if (newGroupPhotoStatus) newGroupPhotoStatus.textContent = 'Photo set';
          })
          .catch(function () {
            wizardUploadingPhoto = false;
            if (newGroupPhotoStatus) newGroupPhotoStatus.textContent = 'Upload failed.';
          });
      });
    }

    function renderReview() {
      if (!newGroupReview) return;
      const name = (newGroupName && newGroupName.value || '').trim() || '(untitled group)';
      const desc = (newGroupDescription && newGroupDescription.value || '').trim();
      const members = Array.from(wizardSelected.values());
      const permission = newGroupMembersCanAdd && newGroupMembersCanAdd.checked ? 'Any member can add people' : 'Admins only can add people';
      newGroupReview.innerHTML =
        '<div class="review-row"><span class="label">Photo</span>' +
        (wizardAvatarUrl ? '<img src="' + escapeHtml(wizardAvatarUrl) + '" style="width:40px;height:40px;border-radius:50%;object-fit:cover">' : '<span>None</span>') +
        '</div>' +
        '<div class="review-row"><span class="label">Name</span><span>' + escapeHtml(name) + '</span></div>' +
        '<div class="review-row"><span class="label">Description</span><span>' + escapeHtml(desc || '—') + '</span></div>' +
        '<div class="review-row"><span class="label">Permissions</span><span>' + escapeHtml(permission) + '</span></div>' +
        '<div class="review-row"><span class="label">Members (' + (members.length + 1) + ')</span>' +
        '<div class="review-members"><span class="review-chip">You (owner)</span>' +
        members.map(function (m) { return '<span class="review-chip">' + escapeHtml(m.display_name || m.username || m.email) + '</span>'; }).join('') +
        '</div></div>';
    }

    document.addEventListener('cc:open-new-group', function () {
      openSheet(newGroupSheet);
      wizardReset();
    });

    if (closeNewGroupBtn) closeNewGroupBtn.addEventListener('click', function () { closeSheet(newGroupSheet); });
    if (newGroupSheet) newGroupSheet.addEventListener('click', function (e) { if (e.target === newGroupSheet) closeSheet(newGroupSheet); });

    if (newGroupNextBtn) {
      newGroupNextBtn.addEventListener('click', function () {
        if (wizardStep === 2 && !(newGroupName && newGroupName.value.trim())) {
          if (newGroupName) newGroupName.focus();
          return;
        }
        if (wizardStep < 4) wizardGoTo(wizardStep + 1);
      });
    }
    if (newGroupBackBtn) {
      newGroupBackBtn.addEventListener('click', function () {
        if (wizardStep > 1) wizardGoTo(wizardStep - 1);
      });
    }

    if (createGroupBtn) {
      createGroupBtn.addEventListener('click', function () {
        if (wizardSubmitting) return; // prevent double submission
        const name = (newGroupName && newGroupName.value || '').trim();
        if (!name) { wizardGoTo(2); if (newGroupName) newGroupName.focus(); return; }
        if (wizardUploadingPhoto) return; // wait for the photo upload to finish
        wizardSubmitting = true;
        createGroupBtn.disabled = true;
        createGroupBtn.textContent = 'Creating…';
        const members = Array.from(wizardSelected.keys());
        api('/groups', {
          method: 'POST',
          body: JSON.stringify({
            name: name,
            members: members,
            avatar: wizardAvatarUrl,
            description: (newGroupDescription && newGroupDescription.value || '').trim(),
            members_can_add: !!(newGroupMembersCanAdd && newGroupMembersCanAdd.checked),
          }),
        }).then(function (res) {
          wizardSubmitting = false;
          createGroupBtn.disabled = false;
          createGroupBtn.textContent = 'Create group';
          if (!res.ok) { alert(res.data.error || 'Could not create group.'); return; }
          closeSheet(newGroupSheet);
          myGroups.unshift(res.data.group);
          renderGroupsTab();
          openGroup(res.data.group);
        }).catch(function () {
          wizardSubmitting = false;
          createGroupBtn.disabled = false;
          createGroupBtn.textContent = 'Create group';
          alert('Could not create group — check your connection and try again.');
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
          const list = res.ok && res.data && Array.isArray(res.data.contacts) ? res.data.contacts : [];
          const already = new Set((g && g.members) || []);
          const remaining = list.filter(function (u) { return !already.has(u.email); });
          if (!addMemberList) return;
          if (!remaining.length) {
            addMemberList.innerHTML = '<div class="current-chat-status">All your contacts are already in this group.</div>';
            return;
          }
          addMemberList.innerHTML = remaining.map(function (u) {
            var displayName = u.display_name || u.username || u.email;
            return '<div class="contact-result"><div class="contact-avatar">' + escapeHtml((displayName || '?').charAt(0).toUpperCase()) + '</div><div><div class="convo-name">' +
              escapeHtml(displayName) + '</div></div><div class="actions"><button type="button" class="btn-new" style="height:34px;padding:0 12px" data-email="' + escapeHtml(u.email) + '">Add</button></div></div>';
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
