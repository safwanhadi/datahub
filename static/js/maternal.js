(() => {
  const fetchForm = document.getElementById('maternal-fetch-form');
  if (fetchForm) {
    fetchForm.addEventListener('submit', (event) => {
      if (fetchForm.dataset.pending === 'true') {
        event.preventDefault();
        return;
      }
      fetchForm.dataset.pending = 'true';
      const button = fetchForm.querySelector('button[type="submit"]');
      button.disabled = true;
      button.textContent = 'Mengambil data…';
      fetchForm.setAttribute('aria-busy', 'true');
      document.getElementById('maternal-fetch-status').textContent = 'Permintaan sedang diproses. Tunggu hingga hasil pengambilan ditampilkan.';
    });
  }
  const form = document.getElementById('maternal-period-filter');
  if (!form) return;
  const period = form.elements.namedItem('period_type');
  const update = () => {
    form.querySelectorAll('[data-period]').forEach((label) => {
      const active = label.dataset.period === period.value;
      label.hidden = !active;
      label.querySelectorAll('select, input').forEach((field) => {
        field.disabled = !active;
      });
    });
  };
  period.addEventListener('change', update);
  update();
})();
