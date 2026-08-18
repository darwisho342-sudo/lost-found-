document.querySelectorAll(".fm-desktop-navigation .nav-link.active").forEach((item) => {
  item.setAttribute("aria-current", "page");
});

document.querySelectorAll("[data-password-toggle]").forEach((button) => {
  button.addEventListener("click", () => {
    const input = button.parentElement.querySelector("input");
    const reveal = input.type === "password";
    input.type = reveal ? "text" : "password";
    button.setAttribute("aria-label", reveal ? button.dataset.hideLabel : button.dataset.showLabel);
    button.querySelector("i").className = reveal ? "bi bi-eye-slash" : "bi bi-eye";
  });
});

const reportForm = document.querySelector("[data-report-form]");
if (reportForm) {
  const types = {
    electronics: ["mobile_phone","laptop","tablet","smartwatch","earbuds","headphones","charger","cable","power_bank","camera","calculator","usb_drive","other","not_sure"], bags: ["backpack","handbag","laptop_bag","school_bag","sports_bag","suitcase","shopping_bag","other","not_sure"],
    clothing: ["jacket","coat","shirt","t_shirt","trousers","dress","shoes","hat","scarf","gloves","other","not_sure"], documents: ["student_id","bank_card","transport_card","driver_licence","national_id","passport","certificate","notebook","other","not_sure"],
    keys: ["house_keys","car_keys","office_keys","locker_key","keychain","electronic_key","other","not_sure"], wallets: ["wallet","purse","card_holder","coin_purse","other","not_sure"], jewellery: ["ring","necklace","bracelet","earrings","watch","other","not_sure"],
    books: ["textbook","notebook","folder","pencil_case","pen","calculator","other","not_sure"], sports_equipment: ["sports_bag","ball","racket","sports_clothing","water_bottle","other","not_sure"], personal_accessories: ["glasses","sunglasses","umbrella","water_bottle","watch","head_covering","other","not_sure"], other: ["other","not_sure"], not_sure: ["not_sure","other"]
  };
  const category = reportForm.querySelector("[name=category]"); const itemType = reportForm.querySelector("[name=item_type]"); const title = reportForm.querySelector("[name=title]");
  let titleWasEdited = Boolean(title && title.value.trim()); if (title) title.addEventListener("input", () => { titleWasEdited = true; });
  const selectedText = (name) => { const control = reportForm.querySelector(`[name=${name}]`); return control && control.selectedOptions && control.value && !["not_sure","no_visible_brand"].includes(control.value) ? control.selectedOptions[0].text : ""; };
  const updateTitle = () => { if (!title || titleWasEdited) return; const city = reportForm.querySelector("[name=city]")?.value.trim(); const parts = [reportForm.dataset.reportType === "found" ? "Found" : "Lost", selectedText("primary_colour"), selectedText("brand"), selectedText("item_type")]; title.value = `${parts.filter(Boolean).join(" ")}${city ? ` in ${city}` : ""}`; };
  const updateTypes = () => { if (!category || !itemType) return; const allowed = new Set(types[category.value] || []); [...itemType.options].forEach((option) => { option.hidden = Boolean(option.value) && !allowed.has(option.value); }); if (itemType.value && !allowed.has(itemType.value)) itemType.value = ""; updateTitle(); };
  const updateConditionals = () => reportForm.querySelectorAll("[data-show-when]").forEach((wrapper) => { const [name, value] = wrapper.dataset.showWhen.split(":"); const control = reportForm.querySelector(`[name=${name}]`); wrapper.hidden = !control || control.value !== value; });
  reportForm.addEventListener("change", (event) => { if (event.target === category) updateTypes(); updateConditionals(); updateTitle(); });
  const details = reportForm.querySelector("[name=additional_details]"); const counter = reportForm.querySelector("[data-character-count]"); const updateCounter = () => { if (counter && details) counter.textContent = details.value.length; }; if (details) details.addEventListener("input", updateCounter);
  const date = reportForm.querySelector("[name=item_date]"); if (date) date.max = new Date().toISOString().slice(0, 10);
  reportForm.querySelector("[data-use-current-location]")?.addEventListener("click", () => { const status = reportForm.querySelector("[data-location-status]"); if (!navigator.geolocation) { status.textContent = "Location is unavailable. Enter the fields manually."; return; } status.textContent = "Requesting location permission…"; navigator.geolocation.getCurrentPosition((position) => { reportForm.querySelector("[name=latitude]").value = position.coords.latitude.toFixed(6); reportForm.querySelector("[name=longitude]").value = position.coords.longitude.toFixed(6); status.textContent = "Coordinates added privately. Country and city must still be entered manually."; }, () => { status.textContent = "Location was not shared. Manual fields remain available."; }, {enableHighAccuracy: false, timeout: 10000, maximumAge: 60000}); });
  const input = reportForm.querySelector("[name=image]"); const editor = reportForm.querySelector("[data-image-editor]"); const canvas = reportForm.querySelector("[data-image-canvas]");
  if (input && editor && canvas) {
    const context = canvas.getContext("2d"); let coverStart = null;
    const replaceUpload = () => canvas.toBlob((blob) => { if (!blob) return; const transfer = new DataTransfer(); transfer.items.add(new File([blob], "prepared-report-image.jpg", {type: "image/jpeg"})); input.files = transfer.files; }, "image/jpeg", .9);
    input.addEventListener("change", () => { const file = input.files[0]; if (!file) { editor.hidden = true; return; } const reader = new FileReader(); reader.onload = () => { const image = new Image(); image.onload = () => { const scale = Math.min(1, 1000 / image.width, 1000 / image.height); canvas.width = Math.round(image.width * scale); canvas.height = Math.round(image.height * scale); context.drawImage(image, 0, 0, canvas.width, canvas.height); editor.hidden = false; replaceUpload(); }; image.src = reader.result; }; reader.readAsDataURL(file); });
    reportForm.querySelector("[data-image-rotate]")?.addEventListener("click", () => { const copy = document.createElement("canvas"); copy.width = canvas.height; copy.height = canvas.width; const target = copy.getContext("2d"); target.translate(copy.width / 2, copy.height / 2); target.rotate(Math.PI / 2); target.drawImage(canvas, -canvas.width / 2, -canvas.height / 2); canvas.width = copy.width; canvas.height = copy.height; context.drawImage(copy, 0, 0); replaceUpload(); });
    reportForm.querySelector("[data-image-crop]")?.addEventListener("click", () => { const x = Math.round(canvas.width * .08), y = Math.round(canvas.height * .08); const copy = document.createElement("canvas"); copy.width = canvas.width - 2*x; copy.height = canvas.height - 2*y; copy.getContext("2d").drawImage(canvas, x, y, copy.width, copy.height, 0, 0, copy.width, copy.height); canvas.width = copy.width; canvas.height = copy.height; context.drawImage(copy, 0, 0); replaceUpload(); });
    reportForm.querySelector("[data-image-cover]")?.addEventListener("click", () => canvas.classList.toggle("cover-mode"));
    canvas.addEventListener("pointerdown", (event) => { if (!canvas.classList.contains("cover-mode")) return; const box = canvas.getBoundingClientRect(); coverStart = {x:(event.clientX-box.left)*canvas.width/box.width,y:(event.clientY-box.top)*canvas.height/box.height}; });
    canvas.addEventListener("pointerup", (event) => { if (!coverStart) return; const box = canvas.getBoundingClientRect(); const x=(event.clientX-box.left)*canvas.width/box.width,y=(event.clientY-box.top)*canvas.height/box.height; context.fillStyle="#111827"; context.fillRect(Math.min(x,coverStart.x),Math.min(y,coverStart.y),Math.abs(x-coverStart.x),Math.abs(y-coverStart.y)); coverStart=null; replaceUpload(); });
    reportForm.querySelector("[data-image-remove]")?.addEventListener("click", () => { input.value=""; context.clearRect(0,0,canvas.width,canvas.height); editor.hidden=true; });
  }
  updateTypes(); updateConditionals(); updateCounter();

  const formElement = reportForm.querySelector("[data-report-form-fields]");
  const wizardActions = reportForm.querySelector("[data-wizard-actions]");
  if (formElement && wizardActions) {
    const directSections = [...formElement.children].filter((element) => element.matches(".form-section"));
    const classification = directSections[0];
    const appearance = directSections[1];
    const location = directSections[2];
    const publicDetails = formElement.querySelector(".expandable-section");
    const privateVerification = formElement.querySelector(".private-verification");
    const privacyReview = formElement.querySelector(".privacy-review");
    const photoSection = directSections.find((section) => section !== privacyReview && section.querySelector("[name=image]"));
    const submitButton = formElement.querySelector("button[name=submission_action][value=submit]");
    const submitActions = submitButton?.closest("div");
    let privatePlaceholder = null;
    if (!privateVerification) {
      privatePlaceholder = document.createElement("section");
      privatePlaceholder.className = "form-section private-verification";
      const placeholderHeading = document.createElement("h2");
      placeholderHeading.className = "h5";
      placeholderHeading.textContent = reportForm.querySelectorAll(".report-progress li")[5]?.textContent.trim() || "";
      privatePlaceholder.appendChild(placeholderHeading);
      formElement.insertBefore(privatePlaceholder, photoSection);
    }
    const steps = [
      [reportForm.querySelector(".report-type-switch")], [classification], [appearance], [location],
      [publicDetails, photoSection], [privateVerification || privatePlaceholder], [privacyReview], [submitActions],
    ].map((group) => group.filter(Boolean));
    const stepNames = [...reportForm.querySelectorAll(".report-progress li")].map((item) => item.textContent.trim());
    const allStepElements = new Set(steps.flat());
    let currentStep = 0;
    const currentNumber = reportForm.querySelector("[data-current-step]");
    const currentName = reportForm.querySelector("[data-current-step-name]");
    const progress = reportForm.querySelector(".report-progress .progress");
    const progressBar = reportForm.querySelector("[data-progress-bar]");
    const back = reportForm.querySelector("[data-step-back]");
    const next = reportForm.querySelector("[data-step-next]");
    const showStep = (index, focusHeading = false) => {
      currentStep = Math.max(0, Math.min(steps.length - 1, index));
      allStepElements.forEach((element) => element.dataset.wizardHidden = "true");
      steps[currentStep].forEach((element) => element.dataset.wizardHidden = "false");
      currentNumber.textContent = currentStep + 1;
      currentName.textContent = stepNames[currentStep] || "";
      progress.setAttribute("aria-valuenow", currentStep + 1);
      progressBar.style.width = `${((currentStep + 1) / steps.length) * 100}%`;
      back.hidden = currentStep === 0;
      next.hidden = currentStep === steps.length - 1;
      if (focusHeading) {
        const heading = steps[currentStep].flatMap((element) => [...element.querySelectorAll("h2,summary")])[0];
        if (heading) { heading.tabIndex = -1; heading.focus(); }
      }
      reportForm.scrollIntoView({behavior: "smooth", block: "start"});
    };
    const stepIsValid = () => {
      const controls = steps[currentStep].flatMap((element) => [...element.querySelectorAll("input,select,textarea")]).filter((control) => !control.disabled && control.type !== "hidden");
      const invalid = controls.find((control) => !control.checkValidity());
      if (invalid) { invalid.reportValidity(); invalid.focus(); return false; }
      return true;
    };
    next.addEventListener("click", () => { if (stepIsValid()) showStep(currentStep + 1, true); });
    back.addEventListener("click", () => showStep(currentStep - 1, true));
    let submitting = false;
    formElement.addEventListener("submit", (event) => {
      if (submitting) { event.preventDefault(); return; }
      if (event.submitter?.value === "draft") return;
      if (!formElement.checkValidity()) {
        event.preventDefault();
        const invalid = formElement.querySelector(":invalid");
        const invalidStep = steps.findIndex((group) => group.some((element) => element.contains(invalid)));
        showStep(invalidStep >= 0 ? invalidStep : 1);
        invalid?.reportValidity();
        return;
      }
      submitting = true;
      event.submitter?.setAttribute("aria-disabled", "true");
    });
    reportForm.classList.add("wizard-active");
    wizardActions.hidden = false;
    const serverError = [...formElement.querySelectorAll(".invalid-feedback")].find((error) => error.textContent.trim());
    const errorStep = serverError ? steps.findIndex((group) => group.some((element) => element.contains(serverError))) : -1;
    showStep(errorStep >= 0 ? errorStep : 0);
  }
}

const filterPanel = document.querySelector("[data-filter-panel]");
if (filterPanel) {
  const openButton = document.querySelector("[data-filter-open]");
  const closeButton = filterPanel.querySelector("[data-filter-close]");
  const backdrop = document.querySelector("[data-filter-backdrop]");
  let returnFocus = null;
  const focusable = () => [...filterPanel.querySelectorAll('button:not([disabled]),a[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled])')].filter((element) => element.offsetParent !== null);
  const close = () => { filterPanel.classList.remove("is-open"); backdrop.classList.remove("is-open"); backdrop.hidden = true; document.body.classList.remove("filter-panel-open"); filterPanel.removeAttribute("role"); filterPanel.removeAttribute("aria-modal"); filterPanel.setAttribute("aria-hidden", "true"); filterPanel.setAttribute("inert", ""); openButton.setAttribute("aria-expanded", "false"); returnFocus?.focus(); };
  const open = () => { returnFocus = document.activeElement; filterPanel.removeAttribute("inert"); filterPanel.removeAttribute("aria-hidden"); filterPanel.classList.add("is-open"); backdrop.hidden = false; backdrop.classList.add("is-open"); document.body.classList.add("filter-panel-open"); filterPanel.setAttribute("role", "dialog"); filterPanel.setAttribute("aria-modal", "true"); openButton.setAttribute("aria-expanded", "true"); closeButton.focus(); };
  openButton?.addEventListener("click", open); closeButton?.addEventListener("click", close); backdrop?.addEventListener("click", close);
  filterPanel.addEventListener("keydown", (event) => { if (event.key === "Escape") close(); if (event.key !== "Tab") return; const items = focusable(); if (!items.length) return; if (event.shiftKey && document.activeElement === items[0]) { event.preventDefault(); items.at(-1).focus(); } else if (!event.shiftKey && document.activeElement === items.at(-1)) { event.preventDefault(); items[0].focus(); } });
  if (window.matchMedia("(max-width: 767.98px)").matches) { filterPanel.setAttribute("inert", ""); filterPanel.setAttribute("aria-hidden", "true"); }
}
