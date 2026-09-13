(function () {
  'use strict';

  document.addEventListener('cc:app-ready', init);

  function init() {
    var app = window.CipherChatApp;
    if (!app) return;
    var strip = document.getElementById('quickContactsStrip');
    if (!strip) return;
    var escapeHtml = app.escapeHtml;

    function render(list) {
      if (!list.length) {
        strip.innerHTML = '';
        return;
      }
      strip.innerHTML = list.map(function (u) {
        var letter = (u.username || u.email || '?').charAt(0).toUpperCase();
        return '<button type="button" class="quick-contact" data-email="' + escapeHtml(u.email) + '" data-username="' + escapeHtml(u.username || u.email) + '">' +
          '<span class="quick-contact-avatar' + (u.online ? ' is-online' : '') + '">' + escapeHtml(letter) + '</span>' +
          '<span class="quick-contact-name">' + escapeHtml((u.username || u.email).split('@')[0]) + '</span>' +
          '</button>';
      }).join('');
      strip.querySelectorAll('.quick-contact').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var socket = app.socket;
          if (socket) socket.emit('initiate_private_chat', { target_email: btn.dataset.email });
        });
      });
    }

    fetch('/get-contacts', { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (list) { render(list || []); })
      .catch(function () { render([]); });
  }
})();
