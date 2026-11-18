document.addEventListener('DOMContentLoaded', function() {
  const navToggle = document.getElementById('nav-toggle');
  const navWrapper = document.getElementById('nav-wrapper');

  if (navToggle && navWrapper) {
    navToggle.addEventListener('click', function() {
      navWrapper.classList.toggle('is-active');
    });
  }
});