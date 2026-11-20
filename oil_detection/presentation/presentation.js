(() => {
  'use strict';
  const slides = Array.from(document.querySelectorAll('.slide'));
  const previous = document.getElementById('previous');
  const next = document.getElementById('next');
  const counter = document.getElementById('counter');
  const progress = document.getElementById('progress');
  let index = 0;

  function show(target, updateHash = true) {
    index = Math.max(0, Math.min(slides.length - 1, target));
    slides.forEach((slide, position) => {
      const active = position === index;
      slide.classList.toggle('active', active);
      slide.setAttribute('aria-hidden', String(!active));
      slide.setAttribute('aria-label', (position + 1) + '-slayd');
    });
    counter.textContent = String(index + 1).padStart(2, '0') + ' / ' + String(slides.length).padStart(2, '0');
    progress.style.width = ((index + 1) / slides.length * 100) + '%';
    previous.disabled = index === 0;
    next.disabled = index === slides.length - 1;
    // Keep direct slide links usable when opened as a local HTML file too.
    if (updateHash && location.hash !== '#' + (index + 1)) {
      history.replaceState(null, '', '#' + (index + 1));
    }
    window.scrollTo(0, 0);
  }

  function fromHash() {
    const value = Number(location.hash.slice(1));
    show(Number.isInteger(value) && value > 0 ? value - 1 : 0, false);
  }

  previous.addEventListener('click', () => show(index - 1));
  next.addEventListener('click', () => show(index + 1));
  document.getElementById('print').addEventListener('click', () => window.print());
  window.addEventListener('hashchange', fromHash);
  document.addEventListener('keydown', event => {
    if (event.altKey || event.ctrlKey || event.metaKey || event.target.closest('input, textarea, select, [contenteditable="true"]')) return;
    const targets = {ArrowRight: index + 1, ArrowLeft: index - 1, PageDown: index + 1, PageUp: index - 1, Home: 0, End: slides.length - 1};
    if (Object.prototype.hasOwnProperty.call(targets, event.key)) {
      event.preventDefault();
      show(targets[event.key]);
    }
  });
  // Printing exposes every page, including to accessibility tools.
  window.addEventListener('beforeprint', () => slides.forEach(slide => slide.removeAttribute('aria-hidden')));
  window.addEventListener('afterprint', () => show(index, false));
  fromHash();
})();
