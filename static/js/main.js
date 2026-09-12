// MAHAY — small UI helpers (no libraries needed)

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
    toggle.textContent = "نمایش";
    toggle.addEventListener("click", () => {
      const isHidden = input.type === "password";
      input.type = isHidden ? "text" : "password";
      toggle.textContent = isHidden ? "پنهان" : "نمایش";
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
  box.innerHTML = `
    <button type="button" class="lightbox-close" aria-label="بستن">&times;</button>
    <button type="button" class="lightbox-prev" aria-label="قبلی">&rsaquo;</button>
    <img alt="">
    <p></p>
    <button type="button" class="lightbox-next" aria-label="بعدی">&lsaquo;</button>`;
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
    if (event.key === "ArrowRight") show(index - 1);  // RTL: right = previous
    if (event.key === "ArrowLeft") show(index + 1);
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
      button.textContent = `${label} (${left.toLocaleString("fa-IR")} ثانیه)`;
      left -= 1;
      setTimeout(tick, 1000);
    };
    tick();
  });
});