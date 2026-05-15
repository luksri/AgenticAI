// content.js — Injected into the active tab to extract page text
// Returns { text, title } to the caller via executeScript result

(function () {
  const title = document.title || "";

  // Remove scripts, styles, nav, footer noise
  const clone = document.body.cloneNode(true);
  for (const tag of clone.querySelectorAll(
    "script, style, noscript, nav, footer, header, aside, [role='navigation'], [role='banner']"
  )) {
    tag.remove();
  }

  // Collapse whitespace
  const text = (clone.innerText || clone.textContent || "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 100000); // cap at 100k chars to avoid massive payloads

  return { text, title };
})();
