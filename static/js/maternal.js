(() => {
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
