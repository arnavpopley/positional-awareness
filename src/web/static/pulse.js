(function () {
  var seen = null;
  var every = 30000;

  function stamp(data) {
    return String(data.filings) + ":" + String(data.scores) + ":" + String(data.yaml);
  }

  function tick() {
    fetch("/api/pulse")
      .then(function (response) {
        return response.json();
      })
      .then(function (data) {
        var next = stamp(data);
        if (seen === null) {
          seen = next;
          return;
        }
        if (next !== seen) {
          window.location.reload();
        }
      })
      .catch(function () {});
  }

  tick();
  setInterval(tick, every);
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) tick();
  });
})();
