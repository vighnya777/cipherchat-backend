document.addEventListener('DOMContentLoaded', function () {
  activatePanelFromHash();
  bindAdminNav();
  bindUserActions();
  bindUserDetailButtons();
  initializeCharts();
});

function activatePanel(panelId) {
  document.querySelectorAll('.admin-panel').forEach(function (panel) {
    panel.classList.add('d-none');
  });
  document.querySelectorAll('.admin-nav-item').forEach(function (item) {
    item.classList.remove('active');
  });
  const target = document.getElementById(panelId);
  const button = document.querySelector(`.admin-nav-item[data-bs-target="#${panelId}"]`);
  if (target) target.classList.remove('d-none');
  if (button) button.classList.add('active');
}

function activatePanelFromHash() {
  const hash = window.location.hash.replace('#', '');
  const valid = ['dashboard', 'users', 'rooms', 'security', 'analytics', 'logs'];
  if (valid.includes(hash)) {
    activatePanel(hash);
  }
}

function bindAdminNav() {
  document.querySelectorAll('.admin-nav-item').forEach(function (button) {
    button.addEventListener('click', function () {
      activatePanel(this.getAttribute('data-bs-target').replace('#', ''));
      window.location.hash = this.getAttribute('data-bs-target');
    });
  });
}

function bindUserActions() {
  document.getElementById('selectAll')?.addEventListener('change', function () {
    document.querySelectorAll('.user-checkbox:not(:disabled)').forEach(function (checkbox) {
      checkbox.checked = this.checked;
    }, this);
  });

  document.querySelectorAll('.role-select').forEach(function (select) {
    select.addEventListener('change', function () {
      updateUserRole(this.dataset.email, this.value, this);
    });
  });
}

function bindUserDetailButtons() {
  document.querySelectorAll('.user-detail-btn').forEach(function (button) {
    button.addEventListener('click', function () {
      const email = this.dataset.email || this.getAttribute('data-email');
      if (email) {
        viewUserDetails(email);
      }
    });
  });
}

function updateUserRole(email, role, element) {
  fetch('/admin/api/update_role', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: email, role: role }),
  })
    .then(function (response) { return response.json(); })
    .then(function (data) {
      if (!data.success) {
        showToast('Unable to update user role.', 'danger');
        if (element) element.value = element.dataset.originalValue || 'user';
      } else {
        showToast('Role updated successfully.', 'success');
        if (element) element.dataset.originalValue = role;
      }
    })
    .catch(function () {
      showToast('Unable to update user role.', 'danger');
      if (element) element.value = element.dataset.originalValue || 'user';
    });
}

function applyBulkAction() {
  const action = document.getElementById('bulkAction').value;
  const emails = Array.from(document.querySelectorAll('.user-checkbox:checked:not(:disabled)'))
    .map(function (checkbox) { return checkbox.value; });
  if (!action || !emails.length) {
    showToast('Select users and an action first.', 'warning');
    return;
  }
  fetch('/admin/api/bulk_action', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ emails: emails, action: action }),
  })
    .then(function (response) { return response.json(); })
    .then(function (data) {
      if (data.success) {
        showToast(`Bulk action completed for ${data.count} users.`, 'success');
        setTimeout(function () { window.location.reload(); }, 800);
      } else {
        showToast('Bulk action failed.', 'danger');
      }
    })
    .catch(function () {
      showToast('Bulk action failed.', 'danger');
    });
}

function refreshStats() {
  fetch('/admin/api/stats')
    .then(function (response) { return response.json(); })
    .then(function (stats) {
      document.getElementById('totalUsers').textContent = stats.total_users;
      document.getElementById('activeUsers').textContent = stats.active_users;
      document.getElementById('pendingUsers').textContent = stats.pending_users;
      document.getElementById('newUsers').textContent = stats.new_users;
      document.getElementById('activePercent').textContent = ((stats.active_users / Math.max(stats.total_users, 1)) * 100).toFixed(1) + '%';
      document.getElementById('systemHealth').innerHTML = `<span class="health-indicator health-${stats.system_health}"></span>${stats.system_health}`;
      document.getElementById('systemUptime').textContent = stats.uptime;
    })
    .catch(function () { showToast('Failed to refresh stats.', 'danger'); });
}

function showToast(message, type) {
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  document.querySelector('.admin-notification-area').appendChild(toast);
  setTimeout(function () { toast.remove(); }, 4000);
}

function initializeCharts() {
  if (typeof Chart === 'undefined') return;
  const activityCtx = document.getElementById('activityChart');
  if (activityCtx) {
    new Chart(activityCtx, {
      type: 'line',
      data: {
        labels: ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'],
        datasets: [{
          label: 'Users',
          data: [12, 18, 14, 20, 22, 28, 25],
          borderColor: '#667eea',
          backgroundColor: 'rgba(102,126,234,0.18)',
          fill: true,
        }, {
          label: 'Messages',
          data: [10, 15, 12, 17, 19, 24, 21],
          borderColor: '#764ba2',
          backgroundColor: 'rgba(118,75,162,0.18)',
          fill: true,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#e2e8f0' } } },
        scales: {
          x: { ticks: { color: '#cbd5e1' }, grid: { color: 'rgba(255,255,255,0.08)' } },
          y: { ticks: { color: '#cbd5e1' }, grid: { color: 'rgba(255,255,255,0.08)' } }
        }
      }
    });
  }
  const currentStats = window.ADMIN_STATS || {};
  const statusCtx = document.getElementById('statusChart');
  if (statusCtx) {
    new Chart(statusCtx, {
      type: 'doughnut',
      data: {
        labels: ['Approved','Pending','Rejected'],
        datasets: [{
          data: [
            currentStats.approved_users || 0,
            currentStats.pending_users || 0,
            currentStats.rejected_users || 0,
          ],
          backgroundColor: ['#28a745', '#ffc107', '#dc3545'],
          borderColor: 'rgba(255,255,255,0.08)',
          borderWidth: 2,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#e2e8f0' } } }
      }
    });
  }
}

function showBroadcastModal() {
  const modalHtml = `
    <div class="admin-modal-overlay" id="broadcastModalOverlay">
      <div class="admin-modal-card">
        <h3>Send Broadcast</h3>
        <textarea id="broadcastMessage" placeholder="Your announcement" rows="5"></textarea>
        <div class="admin-modal-actions">
          <button class="btn btn-secondary btn-sm" onclick="closeBroadcastModal()">Cancel</button>
          <button class="btn btn-primary btn-sm" onclick="sendBroadcast()">Send</button>
        </div>
      </div>
    </div>
  `;
  document.body.insertAdjacentHTML('beforeend', modalHtml);
}

function closeBroadcastModal() {
  document.getElementById('broadcastModalOverlay')?.remove();
}

function sendBroadcast() {
  const message = document.getElementById('broadcastMessage')?.value || '';
  if (!message.trim()) {
    showToast('Enter a broadcast message.', 'warning');
    return;
  }
  fetch('/admin/api/broadcast', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: message.trim() }),
  })
    .then(function (response) { return response.json(); })
    .then(function (data) {
      if (data.success) {
        showToast('Broadcast sent.', 'success');
        closeBroadcastModal();
      } else {
        showToast('Broadcast failed.', 'danger');
      }
    })
    .catch(function () {
      showToast('Broadcast failed.', 'danger');
    });
}

function clearLogs() {
  if (!confirm('Clear all activity logs?')) return;
  fetch('/admin/api/logs/clear', { method: 'POST' })
    .then(function (response) { return response.json(); })
    .then(function (data) {
      if (data.success) {
        showToast('Logs cleared.', 'success');
        setTimeout(function () { window.location.reload(); }, 800);
      } else {
        showToast('Could not clear logs.', 'danger');
      }
    });
}

function showCleanupModal() {
  if (!confirm('Remove inactive rooms?')) return;
  fetch('/admin/api/rooms/cleanup', { method: 'POST' })
    .then(function (response) { return response.json(); })
    .then(function (data) {
      if (data.success) {
        showToast(`Removed ${data.removed} inactive rooms.`, 'success');
        setTimeout(function () { window.location.reload(); }, 800);
      } else {
        showToast('Cleanup failed.', 'danger');
      }
    });
}

function runSystemHealth() {
  fetch('/admin/api/system/health')
    .then(function (response) { return response.json(); })
    .then(function (data) {
      showToast(`System health: ${data.system_health}.`, 'info');
    });
}

function viewUserDetails(email) {
  fetch(`/admin/api/user/${encodeURIComponent(email)}`, {
    headers: {
      'Accept': 'application/json',
      'X-Requested-With': 'XMLHttpRequest',
    },
  })
    .then(function (response) {
      if (!response.ok) {
        throw new Error('request failed');
      }
      return response.json();
    })
    .then(function (data) {
      if (data.error) {
        showToast(data.error === 'not found' ? 'User not found.' : data.error, 'danger');
        return;
      }
      showUserDetailModal(data);
    })
    .catch(function () {
      showToast('Unable to load user details.', 'danger');
    });
}

function showUserDetailModal(user) {
  const profile = user.profile || {};
  const currentRooms = Array.isArray(user.current_rooms) && user.current_rooms.length ? user.current_rooms.join(', ') : 'No active rooms';
  const createdAt = formatUserDate(user.created_at);
  const lastLogin = formatUserDate(user.last_login || user.last_seen);
  const lastSeen = formatUserDate(user.last_seen);

  const modal = document.createElement('div');
  modal.className = 'admin-modal-overlay';
  modal.id = 'userDetailModalOverlay';
  modal.innerHTML = `
    <div class="admin-modal-card" role="dialog" aria-modal="true" aria-labelledby="userDetailTitle">
      <div class="admin-modal-header">
        <div class="admin-user-header">
          <div class="admin-user-avatar">${(user.username || user.email || 'U').charAt(0).toUpperCase()}</div>
          <div>
            <p class="admin-modal-kicker">User profile</p>
            <h3 id="userDetailTitle">${escapeHtml(user.username || 'Unknown user')}</h3>
          </div>
        </div>
        <button class="admin-close-btn" type="button" aria-label="Close" onclick="closeUserDetailModal()">×</button>
      </div>
      <div class="admin-modal-body">
        <div class="user-detail-grid">
          <div class="user-detail-item"><span>Email</span><strong>${escapeHtml(user.email || '—')}</strong></div>
          <div class="user-detail-item"><span>Role</span><strong>${escapeHtml(user.role || 'user')}</strong></div>
          <div class="user-detail-item"><span>Status</span><strong>${escapeHtml(user.status || 'pending')}</strong></div>
          <div class="user-detail-item"><span>Verified</span><strong>${user.verified ? 'Yes' : 'No'}</strong></div>
          <div class="user-detail-item"><span>Created</span><strong>${createdAt}</strong></div>
          <div class="user-detail-item"><span>Last login</span><strong>${lastLogin}</strong></div>
          <div class="user-detail-item"><span>Last seen</span><strong>${lastSeen}</strong></div>
          <div class="user-detail-item"><span>Login count</span><strong>${user.login_count || 0}</strong></div>
        </div>
        <div class="user-detail-section">
          <span>Bio</span>
          <p>${escapeHtml(profile.bio || 'No profile bio provided.')}</p>
        </div>
        <div class="user-detail-section">
          <span>Permissions</span>
          <div class="user-badge-row">
            ${(Array.isArray(user.permissions) && user.permissions.length ? user.permissions : ['standard']).map(function (permission) {
              return `<span class="user-detail-badge">${escapeHtml(permission)}</span>`;
            }).join('')}
          </div>
        </div>
        <div class="user-detail-section">
          <span>Current rooms</span>
          <div class="user-badge-row">
            ${currentRooms === 'No active rooms' ? `<span class="user-detail-badge muted">${escapeHtml(currentRooms)}</span>` : currentRooms.split(', ').map(function (room) { return `<span class="user-detail-badge">${escapeHtml(room)}</span>`; }).join('')}
          </div>
        </div>
        ${(user.status === 'pending') ? `
        <div class="user-detail-section mt-3 pt-3 border-top">
          <button class="btn btn-success btn-sm me-2" onclick="approveUser('${escapeHtml(user.email)}')"><i class="fas fa-check me-1"></i> Approve User</button>
          <button class="btn btn-danger btn-sm" onclick="rejectUser('${escapeHtml(user.email)}')"><i class="fas fa-times me-1"></i> Reject User</button>
        </div>
        ` : ''}
      </div>
    </div>
  `;
  document.body.appendChild(modal);
  modal.addEventListener('click', function (event) {
    if (event.target === modal) closeUserDetailModal();
  });
}

function closeUserDetailModal() {
  const modal = document.getElementById('userDetailModalOverlay');
  if (modal) modal.remove();
}

function approveUser(email) {
  if (!confirm(`Are you sure you want to approve ${email}?`)) return;
  fetch('/admin/api/approve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: email }),
  })
    .then(function (res) { return res.json(); })
    .then(function (data) {
      if (data.success) {
        showToast(`User ${email} approved successfully.`, 'success');
        closeUserDetailModal();
        setTimeout(function () { window.location.reload(); }, 600);
      } else {
        showToast(data.error || data.message || 'Failed to approve user.', 'danger');
      }
    })
    .catch(function () {
      showToast('Error approving user.', 'danger');
    });
}

function rejectUser(email) {
  if (!confirm(`Are you sure you want to reject ${email}?`)) return;
  fetch('/admin/api/reject', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: email }),
  })
    .then(function (res) { return res.json(); })
    .then(function (data) {
      if (data.success) {
        showToast(`User ${email} rejected.`, 'warning');
        closeUserDetailModal();
        setTimeout(function () { window.location.reload(); }, 600);
      } else {
        showToast(data.error || data.message || 'Failed to reject user.', 'danger');
      }
    })
    .catch(function () {
      showToast('Error rejecting user.', 'danger');
    });
}

function formatUserDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
