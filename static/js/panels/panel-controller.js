(function () {
  'use strict';

  document.addEventListener('cc:app-ready', init);

  function init() {
    var body = document.body;
    var chatMainHeader = document.getElementById('chatMainHeader');
    if (!body || !chatMainHeader) return;

    body.classList.add('cc-panels');

    var backBtn = document.createElement('button');
    backBtn.type = 'button';
    backBtn.className = 'cc-panel-back';
    backBtn.setAttribute('aria-label', 'Back to chats');
    backBtn.innerHTML = '<i class="bi bi-arrow-left"></i>';
    var currentChatInfo = chatMainHeader.querySelector('.current-chat-info');
    if (currentChatInfo) chatMainHeader.insertBefore(backBtn, currentChatInfo);

    function showChatPanel() {
      body.classList.add('cc-panel-chat');
    }
    function showListPanel() {
      body.classList.remove('cc-panel-chat');
    }

    backBtn.addEventListener('click', showListPanel);

    ['conversationsList', 'contactsList', 'groupsList'].forEach(function (id) {
      var list = document.getElementById(id);
      if (!list) return;
      list.addEventListener('click', function (e) {
        if (window.matchMedia('(max-width: 800px)').matches) showChatPanel();
      });
    });
  }
})();
