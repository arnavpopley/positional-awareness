const { authorized } = require("./auth");
const fs = require("fs");
const path = require("path");

function readBundle() {
  const file = path.join(__dirname, "bundle.json");
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

module.exports = (req, res) => {
  if (!authorized(req)) {
    res.writeHead(303, { Location: "/login" });
    res.end();
    return;
  }
  let p = "/";
  try {
    const url = new URL(req.url, "http://local");
    p = url.searchParams.get("p") || "/";
  } catch {
    p = "/";
  }
  if (!p.startsWith("/")) p = "/" + p;
  if (p.length > 1 && p.endsWith("/")) p = p.slice(0, -1);
  const bundle = readBundle();
  const html = bundle[p];
  if (!html) {
    res.statusCode = 404;
    res.setHeader("Content-Type", "text/plain; charset=utf-8");
    res.end("not found");
    return;
  }
  res.setHeader("Content-Type", "text/html; charset=utf-8");
  res.setHeader("Cache-Control", "private, no-store");
  res.end(html);
};
