(() => {
  const form = document.querySelector('[data-bulk-form]');
  if (!form) return;
  const all = form.querySelector('[data-select-all]');
  const boxes = [...form.querySelectorAll('[data-report-checkbox]')];
  const counter = form.querySelector('[data-selected-count]');
  const update = () => {
    const selected = boxes.filter((box) => box.checked).length;
    counter.textContent = selected;
    all.checked = boxes.length > 0 && selected === boxes.length;
    all.indeterminate = selected > 0 && selected < boxes.length;
  };
  all.addEventListener('change', () => { boxes.forEach((box) => { box.checked = all.checked; }); update(); });
  boxes.forEach((box) => box.addEventListener('change', update));
  form.addEventListener('submit', (event) => {
    if (!boxes.some((box) => box.checked)) {
      event.preventDefault();
      window.alert(form.dataset.selectionRequired);
    }
  });
  update();
})();
