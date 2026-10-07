document.addEventListener('submit',function(e){const msg=e.target.getAttribute('data-confirm');if(msg&&!window.confirm(msg))e.preventDefault();});


// V2.3.2 - Fenêtre modale pour l'effacement d'un compte
document.addEventListener('DOMContentLoaded', function () {
  const modal = document.getElementById('erase-modal');
  if (!modal) return;

  const userLabel = document.getElementById('erase-modal-user');
  const userInput = document.getElementById('erase-modal-user-input');
  const confirmation = document.getElementById('erase-modal-confirmation');

  function openEraseModal(userId) {
    userLabel.textContent = userId || '';
    userInput.value = userId || '';
    confirmation.value = '';
    modal.hidden = false;
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('modal-open');
    window.setTimeout(() => confirmation.focus(), 0);
  }

  function closeEraseModal() {
    modal.hidden = true;
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('modal-open');
    confirmation.value = '';
  }

  document.querySelectorAll('.js-open-erase').forEach(function (button) {
    button.addEventListener('click', function () {
      openEraseModal(button.dataset.userId);
    });
  });

  modal.querySelectorAll('.js-close-erase').forEach(function (button) {
    button.addEventListener('click', closeEraseModal);
  });

  modal.addEventListener('click', function (event) {
    if (event.target === modal) closeEraseModal();
  });

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && !modal.hidden) closeEraseModal();
  });
});
