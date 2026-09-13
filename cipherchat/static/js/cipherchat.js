document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.flash button').forEach((button) => button.addEventListener('click', () => button.closest('.flash').remove()));
  window.setTimeout(() => document.querySelectorAll('.flash').forEach((item) => item.remove()), 5500);
  if (window.lucide) window.lucide.createIcons();
});

class CipherModal {
  constructor(element) { this.element = element; if (element) element.__cipherModal = this; }
  show() { this.element?.classList.add('is-open'); }
  hide() { this.element?.classList.remove('is-open'); }
  static getInstance(value) { return value instanceof CipherModal ? value : value?.__cipherModal || null; }
}

window.bootstrap = window.bootstrap || {
  Modal: CipherModal,
  Alert: class { constructor(element) { this.element = element; } close() { this.element?.remove(); } },
  Toast: class { constructor(element) { this.element = element; } show() { this.element?.classList.add('show'); } },
};
