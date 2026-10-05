// MAHAY — small UI helpers (no libraries needed)

// The words this script writes on the page come from the page itself (data-text-* on <body>, in
// the page's language). A page without them (the admin panel) is Persian.
const uiText = (name, persian) => document.body?.dataset[`text${name}`] || persian;
const isRtl = () => document.documentElement.dir !== "ltr";

document.addEventListener("DOMContentLoaded", () => {
  // 1) Show / hide password button for every password field
  document.querySelectorAll('input[type="password"]').forEach((input) => {
    const wrap = document.createElement("div");
    wrap.className = "password-wrap";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "password-toggle";
    toggle.textContent = uiText("Show", "نمایش");
    toggle.addEventListener("click", () => {
      const isHidden = input.type === "password";
      input.type = isHidden ? "text" : "password";
      toggle.textContent = isHidden ? uiText("Hide", "پنهان") : uiText("Show", "نمایش");
    });
    wrap.appendChild(toggle);
  });

  // 2) Messages (toasts): close button + auto-hide after 5 seconds
  document.querySelectorAll(".toast").forEach((toast) => {
    const close = () => {
      toast.classList.add("is-hiding");
      setTimeout(() => toast.remove(), 300);
    };
    toast.querySelector(".toast-close")?.addEventListener("click", close);
    setTimeout(close, 5000);
  });

  // 3) Prevent double submit: disable the button and show a spinner
  document.querySelectorAll("form").forEach((form) => {
    form.addEventListener("submit", () => {
      const button = form.querySelector('button[type="submit"]');
      if (button) {
        button.disabled = true;
        button.classList.add("is-loading");
      }
    });
  });
});

// When the user comes back with the browser "Back" button, re-enable buttons
window.addEventListener("pageshow", () => {
  document.querySelectorAll("button.is-loading").forEach((button) => {
    button.disabled = false;
    button.classList.remove("is-loading");
  });
});


// 4) Image gallery lightbox: <a href="big.jpg" data-lightbox="group" data-caption="...">
document.addEventListener("DOMContentLoaded", () => {
  const links = [...document.querySelectorAll("a[data-lightbox]")];
  if (!links.length) return;

  let index = 0;
  const box = document.createElement("div");
  box.className = "lightbox";
  box.hidden = true;
  // The arrows point the way the page reads: «previous» is at the start of the line (right in Persian)
  box.innerHTML = `
    <button type="button" class="lightbox-close">&times;</button>
    <button type="button" class="lightbox-prev">${isRtl() ? "&rsaquo;" : "&lsaquo;"}</button>
    <img alt="">
    <p></p>
    <button type="button" class="lightbox-next">${isRtl() ? "&lsaquo;" : "&rsaquo;"}</button>`;
  box.querySelector(".lightbox-close").setAttribute("aria-label", uiText("Close", "بستن"));
  box.querySelector(".lightbox-prev").setAttribute("aria-label", uiText("Previous", "قبلی"));
  box.querySelector(".lightbox-next").setAttribute("aria-label", uiText("Next", "بعدی"));
  document.body.appendChild(box);
  const image = box.querySelector("img");
  const caption = box.querySelector("p");

  const show = (i) => {
    index = (i + links.length) % links.length;
    image.src = links[index].href;
    caption.textContent = links[index].dataset.caption || "";
    box.hidden = false;
  };
  const close = () => { box.hidden = true; };

  links.forEach((link, i) => link.addEventListener("click", (event) => { event.preventDefault(); show(i); }));
  box.querySelector(".lightbox-close").addEventListener("click", close);
  box.querySelector(".lightbox-prev").addEventListener("click", () => show(index - 1));
  box.querySelector(".lightbox-next").addEventListener("click", () => show(index + 1));
  box.addEventListener("click", (event) => { if (event.target === box) close(); });
  document.addEventListener("keydown", (event) => {
    if (box.hidden) return;
    if (event.key === "Escape") close();
    // The arrow key toward the start of the line goes back: right in Persian, left in English
    const back = isRtl() ? "ArrowRight" : "ArrowLeft";
    const forward = isRtl() ? "ArrowLeft" : "ArrowRight";
    if (event.key === back) show(index - 1);
    if (event.key === forward) show(index + 1);
  });
});


// 5) Light / dark theme button (the choice is remembered in this browser)
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".theme-toggle").forEach((button) => {
    button.addEventListener("click", () => {
      const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      localStorage.setItem("theme", next);
    });
  });
});


// 6) "Send the code again": stays disabled until the waiting time is over
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("button[data-resend-in]").forEach((button) => {
    let left = Number(button.dataset.resendIn || 0);
    const label = button.textContent;
    if (left <= 0) return;

    const tick = () => {
      if (left <= 0) {
        button.disabled = false;
        button.textContent = label;
        return;
      }
      button.disabled = true;
      const seconds = left.toLocaleString(document.documentElement.lang === "en" ? "en-US" : "fa-IR");
      button.textContent = `${label} (${seconds} ${uiText("Seconds", "ثانیه")})`;
      left -= 1;
      setTimeout(tick, 1000);
    };
    tick();
  });
});

// 7) A follow-up question shown only for the answer it follows:
//    <input data-show-when="heard_from=other"> sits in its .field, hidden until «سایر» is picked.
//    Without this script the box is simply always there.
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-show-when]").forEach((input) => {
    if (!input.form) return;
    const [name, value] = input.dataset.showWhen.split("=");
    const field = input.closest(".field") || input;
    const radios = [...input.form.querySelectorAll(`input[name="${name}"]`)];
    const update = () => {
      field.hidden = !radios.some((radio) => radio.checked && radio.value === value);
    };
    radios.forEach((radio) => radio.addEventListener("change", update));
    update();
  });
});
