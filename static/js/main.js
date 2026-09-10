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