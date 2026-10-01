/* Money inputs (domains/widgets.py MoneyInput): group the digits while typing and read the amount
   out in words under the field. The server strips the grouping again, so this is display only. */
'use strict';
{
  const FA = '۰۱۲۳۴۵۶۷۸۹';
  const AR = '٠١٢٣٤٥٦٧٨٩';
  const toLatin = (text) => text
    .replace(/[۰-۹]/g, (d) => FA.indexOf(d))
    .replace(/[٠-٩]/g, (d) => AR.indexOf(d));
  const toFa = (number) => String(number).replace(/\d/g, (d) => FA[d]);
  const group = (digits) => digits.replace(/\B(?=(\d{3})+(?!\d))/g, ',');

  // 1250000 → «۱ میلیون و ۲۵۰ هزار»
  const inWords = (digits) => {
    let rest = Number(digits);
    if (!rest) return toFa(0);
    const parts = [];
    for (const [size, name] of [[1e9, 'میلیارد'], [1e6, 'میلیون'], [1e3, 'هزار']]) {
      const count = Math.floor(rest / size);
      if (count) {
        parts.push(`${toFa(count)} ${name}`);
        rest -= count * size;
      }
    }
    if (rest) parts.push(toFa(rest));
    return parts.join(' و ');
  };

  const bind = (input) => {
    const unit = input.dataset.unit || '';
    const words = input.id ? document.querySelector(`.money-words[data-for="${input.id}"]`) : null;
    const render = () => {
      const fromEnd = input.value.length - (input.selectionEnd ?? input.value.length);
      const digits = toLatin(input.value).replace(/\D/g, '').replace(/^0+(?=\d)/, '');
      const shown = group(digits);
      if (shown !== input.value) {
        input.value = shown;
        if (document.activeElement === input) {
          const at = Math.max(0, shown.length - fromEnd);
          input.setSelectionRange(at, at);
        }
      }
      if (words) words.textContent = digits ? `${inWords(digits)} ${unit}` : '';
    };
    input.addEventListener('input', render);
    render();
  };

  // form media is loaded in <head>, before the inputs exist
  const start = () => document.querySelectorAll('input.money-input').forEach(bind);
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
}
