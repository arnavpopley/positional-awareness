(function () {
  var every = 30000;

  function fill() {
    fetch("/api/quotes", { credentials: "same-origin" })
      .then(function (response) {
        if (!response.ok) throw new Error("quotes");
        return response.json();
      })
      .then(function (data) {
        Object.keys(data).forEach(function (symbol) {
          var quote = data[symbol];
          var cmpVal = quote.cmp || quote.last;
          var qty = document.getElementById("qty-" + symbol);
          var cost = document.getElementById("cost-" + symbol);
          var cmp = document.getElementById("cmp-" + symbol);
          var ret = document.getElementById("ret-" + symbol);
          if (qty && quote.qty) qty.textContent = quote.qty;
          if (cost && quote.cost) cost.textContent = quote.cost;
          if (cmp) cmp.textContent = cmpVal;
          if (ret) {
            ret.textContent = quote.ret;
            ret.classList.toggle("up", quote.up);
            ret.classList.toggle("down", quote.down);
          }
        });
      })
      .catch(function () {});
  }

  fill();
  setInterval(fill, every);
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) fill();
  });
})();
