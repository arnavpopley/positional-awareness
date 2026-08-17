fetch("/api/quotes")
  .then(function (response) {
    return response.json();
  })
  .then(function (data) {
    Object.keys(data).forEach(function (symbol) {
      var quote = data[symbol];
      var cmp = document.getElementById("cmp-" + symbol);
      var ret = document.getElementById("ret-" + symbol);
      if (cmp) cmp.textContent = quote.cmp;
      if (ret) {
        ret.textContent = quote.ret;
        ret.classList.toggle("up", quote.up);
        ret.classList.toggle("down", quote.down);
      }
    });
  })
  .catch(function () {});
