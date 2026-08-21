document.addEventListener('DOMContentLoaded', function() {
  // Add self-linking anchors to headings
  document.querySelectorAll('h1[id], h2[id], h3[id], h4[id], h5[id], h6[id]').forEach(function(heading) {
    const id = heading.getAttribute('id');
    if (id) {
      const anchor = document.createElement('a');
      anchor.setAttribute('href', '#' + id);
      anchor.innerHTML = heading.innerHTML;
      heading.innerHTML = '';
      heading.appendChild(anchor);
    }
  });
});