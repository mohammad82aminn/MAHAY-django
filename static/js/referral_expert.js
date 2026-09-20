/*
 * Referral rows: show only the experts who manage the domain picked in that same row.
 *
 * Every option arrives tagged with data-domains (see services/widgets.py). The full list is kept
 * aside the first time a row is touched, so narrowing it is never destructive: change the domain
 * again and the right names come back.
 */
(function () {
  "use strict";

  var ROW = "tr, .inline-related";

  function allOptions(select) {
    if (!select.dataset.loaded) {
      select._options = Array.prototype.map.call(select.options, function (option) {
        return {
          value: option.value,
          text: option.text,
          domains: (option.dataset.domains || "").split(" ").filter(Boolean),
        };
      });
      select.dataset.loaded = "1";
    }
    return select._options;
  }

  function refresh(row) {
    if (!row || !row.querySelector) return;
    var domain = row.querySelector('select[name$="-domain"]');
    var expert = row.querySelector('select[name$="-expert"]');
    if (!domain || !expert) return;

    var chosen = domain.value;
    var wanted = expert.value;
    var fragment = document.createDocumentFragment();

    allOptions(expert).forEach(function (item) {
      var fits = !item.value || !chosen || item.domains.indexOf(chosen) !== -1;
      if (!fits) return;
      var option = document.createElement("option");
      option.value = item.value;
      option.text = item.text;
      if (item.domains.length) option.dataset.domains = item.domains.join(" ");
      fragment.appendChild(option);
    });

    expert.innerHTML = "";
    expert.appendChild(fragment);
    // Keep the choice when it still fits the new domain, drop it when it does not
    expert.value = Array.prototype.some.call(expert.options, function (option) {
      return option.value === wanted;
    })
      ? wanted
      : "";
  }

  function refreshAll() {
    document.querySelectorAll('select[name$="-expert"]').forEach(function (expert) {
      refresh(expert.closest(ROW));
    });
  }

  document.addEventListener("change", function (event) {
    if (event.target.matches && event.target.matches('select[name$="-domain"]')) {
      refresh(event.target.closest(ROW));
    }
  });

  document.addEventListener("DOMContentLoaded", refreshAll);
  // Django fires this on the new row when "add another" is used
  document.addEventListener("formset:added", function (event) {
    refresh(event.target);
  });
})();
