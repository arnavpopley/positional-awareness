const { token } = require("./auth");

function parseBody(req) {
  return new Promise((resolve, reject) => {
    let raw = "";
    req.on("data", (chunk) => {
      raw += chunk;
      if (raw.length > 4096) {
        req.destroy();
        reject(new Error("too large"));
      }
    });
    req.on("end", () => resolve(new URLSearchParams(raw)));
    req.on("error", reject);
  });
}

module.exports = async (req, res) => {
  if (req.method !== "POST") {
    res.writeHead(303, { Location: "/login" });
    res.end();
    return;
  }
  const secret = process.env.PA_SITE_PASSWORD || "";
  let body;
  try {
    body = await parseBody(req);
  } catch {
    res.writeHead(303, { Location: "/login?bad=1" });
    res.end();
    return;
  }
  if (!secret || body.get("password") !== secret) {
    res.writeHead(303, { Location: "/login?bad=1" });
    res.end();
    return;
  }
  const secure = process.env.VERCEL_ENV === "production" ? "; Secure" : "";
  res.writeHead(303, {
    Location: "/",
    "Set-Cookie": `pa_gate=${token(secret)}; HttpOnly${secure}; SameSite=Lax; Path=/; Max-Age=2592000`,
  });
  res.end();
};
