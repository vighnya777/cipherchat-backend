document.addEventListener('DOMContentLoaded', function () {
  activatePanelFromHash();
  bindAdminNav();
  bindUserActions();
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
  window.location.href = `/admin/api/user/${encodeURIComponent(email)}`;
}
